"""
RAG Pipeline with Adaptive Routing (Traffic Cop).

Beginner Note: This file decides whether a user's question needs the expensive
AI (Gemini) or can be answered instantly from the database. We call this
"Adaptive Routing" because we route each query to the cheapest channel that
can answer it correctly.

Think of it as a traffic cop at an intersection:
  - If the driver asks "What's the price?" → point them to the database (fast, free).
  - If the driver asks "Is this safe for a pregnant patient?" → point them to Gemini (slow, costly).
"""

import asyncio
import hashlib
import json
import logging
import re
from sqlalchemy.orm import Session
from app.core.config import get_application_settings
# Lazy import: execute_clinical_search is imported inside the function
# to avoid loading sentence_transformers (and its heavy torch/torchaudio
# dependencies) at module level. This keeps the module importable even
# when the full ML stack is not available.
# from app.services.semantic_search import execute_clinical_search
from app.infrastructure.models import MedicationBatchModel, MedicationModel
from app.services.rule_engine import ClinicalSafetyJudge
from app.domain.schemas import ClinicalNarrativeSchema
from app.core.circuit_breaker import AegisLiteCircuitBreaker, CircuitStateEnum
from app.core.cache import get_global_db_version, CACHE_TTL_SECONDS
from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gemini-Specific Circuit Breaker
# ---------------------------------------------------------------------------
# Beginner Note: We create a SEPARATE circuit breaker instance for Gemini
# API calls. The existing AegisLiteCircuitBreaker was designed for ML model
# predictions (stockout forecasts). We reuse the same class but with more
# sensitive thresholds because LLM APIs fail more often and we need to
# react faster.
#
#   failure_threshold = 3   → Open after 3 consecutive failures.
#   recovery_timeout  = 30  → Try recovery after 30 seconds.
#   success_threshold = 2   → Close after 2 consecutive successes.
#
# This instance is created once at module load and shared across all
# requests (singleton pattern via the wrapper function below).
_gemini_circuit_breaker_instance = None


def get_gemini_circuit_breaker() -> AegisLiteCircuitBreaker:
    """
    Get the Gemini-specific circuit breaker singleton.

    Returns:
        An AegisLiteCircuitBreaker configured for LLM API calls.
    """
    global _gemini_circuit_breaker_instance
    if _gemini_circuit_breaker_instance is None:
        _gemini_circuit_breaker_instance = AegisLiteCircuitBreaker(
            failure_threshold=3,
            recovery_timeout=30,
            success_threshold=2,
        )
    return _gemini_circuit_breaker_instance


# =====================================================================
# ADAPTIVE ROUTING: THE TRAFFIC COP
# =====================================================================
# This function acts as a middleware router. It inspects the user's query
# BEFORE deciding whether to call the expensive Gemini API or query the
# database directly.
#
# Why do we need this?
#   - Every call to Gemini costs money (even if it's just $0.01 per call).
#   - Many pharmacy questions are simple database lookups (e.g., "What is
#     the MRP?", "How many units in stock?").
#   - Calling Gemini for these simple questions is a waste of money AND
#     adds 2-3 seconds of latency.
#
# The solution: Check for objective keywords first. If found, answer from
# the database instantly (0 latency, $0 cost). Only fall through to Gemini
# for complex clinical questions that require real AI reasoning.

# The list of keywords that indicate an objective, fact-based question.
# These are questions that can be answered by simply querying the database
# without any AI reasoning.
OBJECTIVE_KEYWORDS_LIST = [
    "mrp",
    "price",
    "stock",
    "quantity",
    "available",
    "cost",
    "expiry",
    "expire",
    "expires",
    "expiration",
    "mfg",
    "manufacture",
    "batch",
]


async def route_and_process_query(
    db: Session,
    query: str,
    sku_id: str = None,
    intents: dict = None,
) -> dict:
    """
    Route a query to either the database (for objective questions) or
    Gemini RAG (for clinical/subjective questions).

    Parameters:
        db: Active database session.
        query: The user's natural language question.
        sku_id: Optional SKU identifier if the frontend knows which
                medication the user is asking about.
        intents: Optional dict of extracted intents from QuerySanitizer.
                 Passed to the Rule Engine for deterministic safety checks
                 before the LLM is called. Expected keys: 'pregnancy',
                 'pediatric', 'substitute', 'objective'.

    Returns:
        dict with keys "answer" (str), "context_used" (list),
        "is_safe_to_dispense" (bool), "system_lock_reason" (str | None),
        and "citations" (list). Matches the return format of
        generate_clinical_response() so the caller doesn't need to
        know which route was taken.
    """
    # =====================================================================
    # STEP 0: EXTRACT SKU FROM QUERY TEXT (if not already provided)
    # =====================================================================
    # Beginner Note: The frontend might not always know which SKU the user
    # is asking about. For example, if the user types "What is the price
    # of DOLO-650?" directly in a chat box, the frontend sends sku_id=None.
    # We use a regex to extract the SKU directly from the query text.
    #
    # We try two patterns:
    #   1. Standard format with hyphen (e.g., "AMOXI-500", "PAN-40").
    #   2. No hyphen format (e.g., "PAN40", "DOLO650") — we insert the
    #      hyphen before the trailing digits so it matches the database.
    # =====================================================================
    if sku_id is None:
        # Pattern 1: "AMOXI-500", "PAN-40", "dolo-650" (case-insensitive)
        sku_match = re.search(r"([A-Z]+)-(\d+)", query, re.IGNORECASE)
        if sku_match:
            sku_id = f"{sku_match.group(1).upper()}-{sku_match.group(2)}"
            logger.info(
                f"Adaptive Router: Extracted SKU '{sku_id}' from query "
                f"(hyphenated pattern)."
            )
        else:
            # Pattern 2: "PAN40", "AMOXI500", "dolo650" (no hyphen)
            sku_match = re.search(r"([A-Z]+)(\d+)", query, re.IGNORECASE)
            if sku_match:
                sku_id = f"{sku_match.group(1).upper()}-{sku_match.group(2)}"
                logger.info(
                    f"Adaptive Router: Extracted SKU '{sku_id}' from query "
                    f"(no-hyphen pattern — hyphen inserted)."
                )

    # =====================================================================
    # STEP 1: CHECK IF THIS IS AN OBJECTIVE DATABASE QUERY
    # =====================================================================
    # We convert the query to lowercase so that "MRP" matches "mrp" and
    # "Price" matches "price". Case-insensitive matching is critical for
    # real-world use because pharmacists type in all sorts of ways.
    query_lowercase = query.lower()

    # Check if any of the objective keywords appear in the user's query.
    # We use a simple loop (not a one-liner) so a junior developer can
    # clearly see the logic.
    is_pricing_query = False
    for keyword in OBJECTIVE_KEYWORDS_LIST:
        if keyword in query_lowercase:
            is_pricing_query = True
            logger.info(
                f"Adaptive Router: Detected objective keyword '{keyword}' "
                f"in query. Will route to database."
            )
            break

    # =====================================================================
    # STEP 2: ROUTE TO DATABASE (if objective query AND we have a SKU)
    # =====================================================================
    # Beginner Note: We need sku_id to answer objective queries because
    # "what's the price?" is meaningless without knowing WHICH medication
    # the user is asking about. If the frontend didn't provide sku_id, we
    # fall through to Gemini which can infer context from the query text.
    if is_pricing_query and sku_id is not None:
        # Query all batches of this medication from the database.
        # We fetch all batches because the user might want aggregate info
        # like total stock (sum of all batches) or earliest expiry.
        medication_batches = db.query(MedicationBatchModel).filter(
            MedicationBatchModel.sku_id == sku_id
        ).order_by(
            MedicationBatchModel.expiry_date.asc()
        ).all()

        if medication_batches:
            # Calculate aggregate values across all batches
            total_stock = sum(
                batch.available_quantity for batch in medication_batches
            )
            lowest_price = min(
                batch.max_retail_price for batch in medication_batches
            )
            earliest_expiry = medication_batches[0].expiry_date

            # Format a natural-sounding answer string.
            # We include the batch-level details so the pharmacist has
            # full visibility into each batch's status.
            formatted_answer = (
                f"SKU {sku_id} — "
                f"MRP: ₹{lowest_price:.2f}, "
                f"Total Stock: {total_stock} units, "
                f"Earliest Expiry: {earliest_expiry.isoformat()}. "
            )

            logger.info(
                f"Adaptive Router: Answered objective query from database. "
                f"SKU={sku_id}, Stock={total_stock}, MRP=₹{lowest_price}"
            )

            return {
                "answer": formatted_answer,
                "context_used": [],
                "is_safe_to_dispense": True,
                "system_lock_reason": None,
                "citations": [],
            }

        else:
            # No batches found in the database for this SKU.
            return {
                "answer": (
                    f"No inventory records found for SKU '{sku_id}'. "
                    "Please verify the SKU or check inventory master."
                ),
                "context_used": [],
                "is_safe_to_dispense": True,
                "system_lock_reason": None,
                "citations": [],
            }

    # =====================================================================
    # STEP 3: FALL-THROUGH TO GEMINI RAG (Clinical/Subjective questions)
    # =====================================================================
    # If we reached this point, one of two things is true:
    #   1. The query is a clinical/subjective question (e.g., "Is this safe
    #      for a patient with liver disease?") — this REQUIRES AI reasoning.
    #   2. The query matches objective keywords but no sku_id was provided
    #      — we send it to Gemini so it can try to infer the medication
    #      from the context of the conversation.
    #
    # In both cases, we delegate to the existing generate_clinical_response()
    # function which handles the full Retrieval-Augmented Generation pipeline.

    logger.info(
        "Adaptive Router: No objective database match found. "
        "Routing to Gemini RAG pipeline."
    )

    return await generate_clinical_response(
        db=db,
        query=query,
        sku_id=sku_id,
        intents=intents or {},
    )


async def generate_clinical_response(
    db: Session,
    query: str,
    sku_id: str = None,
    intents: dict = None,
) -> dict:
    """
    Retrieval-Augmented Generation (RAG) Pipeline.

    Refactored for Phase 3:
        Step A — Retrieval (get clinical context via PubMedBERT vector search)
        Step B — Rule Engine (deterministic safety check BEFORE Gemini)
        Step C — Prompt building (with Judge's verdict injected)
        Step D — Structured Gemini generation (JSON output enforced)
        Step E — Parse & return (validate Gemini's JSON against ClinicalNarrativeSchema)

    Returns:
        dict with keys:
            "answer" (str)
            "context_used" (list)
            "is_safe_to_dispense" (bool)
            "system_lock_reason" (str | None)
            "citations" (list of str)
    """
    # Guard: ensure intents is always a dict so we can call .get() safely
    if intents is None:
        intents = {}

    # =====================================================================
    # STEP 0: DYNAMIC API KEY CONFIGURATION
    # =====================================================================
    # We fetch the application settings at runtime instead of module load time.
    # This guarantees we have the latest environment variables loaded safely.
    # Lazy import: google.generativeai is only imported when RAG is actually used.
    #
    # Beginner Note: We wrap the import AND configuration in a try/except
    # because the google-generativeai library might not be installed in all
    # environments (e.g., CI/CD, offline dev). Without this guard, a missing
    # import would raise an unhandled ModuleNotFoundError and return a 500
    # error to the user — which is a terrible experience. Instead, we log
    # the error and return a clean message telling the user to check their
    # API configuration.
    try:
        import google.generativeai as genai
        settings = get_application_settings()
        if settings.GEMINI_API_KEY:
            genai.configure(api_key=settings.GEMINI_API_KEY)
        else:
            logger.warning("GEMINI_API_KEY is missing. RAG pipeline will fail if called.")
    except (ImportError, Exception) as e:
        logger.error(f"Gemini module or configuration error: {str(e)}")
        return {
            "answer": "AI Generation Offline: Check API Configuration.",
            "context_used": [],
            "is_safe_to_dispense": True,
            "system_lock_reason": None,
            "citations": [],
        }

    # =====================================================================
    # STEP 1: RETRIEVAL (Get the facts from our database)
    # =====================================================================
    # We query the vector database for the top 3 most relevant clinical guidelines.
    # Lazy import: Only load sentence_transformers when clinical RAG is actually needed.
    from app.services.semantic_search import execute_clinical_search
    search_results = execute_clinical_search(db=db, query=query, sku_id=sku_id, top_k=3)

    # If the safety breaker tripped (no high-confidence results), degrade gracefully.
    if search_results.get("safety_warning"):
        return {
            "answer": search_results["safety_warning"],
            "context_used": [],
            "is_safe_to_dispense": True,
            "system_lock_reason": None,
            "citations": [],
        }

    context_items = search_results["results"]

    # =====================================================================
    # STEP 1.5: ENRICH RETRIEVED RECORDS WITH MEDICATION SAFETY DATA
    # =====================================================================
    # Beginner Note: The clinical_search returns records from the
    # clinical_knowledge_base table, which does NOT contain pregnancy
    # categories or pediatric age thresholds. Those live in the
    # medications table. We look up the medication record here and
    # add its safety fields to the retrieved records so the Judge
    # has all the data it needs.
    enriched_records = list(context_items)

    if sku_id:
        try:
            medication_record = db.query(MedicationModel).filter(
                MedicationModel.sku_id == sku_id
            ).first()

            if medication_record:
                # Create a synthetic record carrying the medication's
                # safety data so the Rule Engine can inspect it.
                safety_enrichment = {
                    "sku_id": medication_record.sku_id,
                    "content": "",
                    "pregnancy_category": medication_record.pregnancy_category,
                    "pediatric_age_threshold_months": (
                        medication_record.pediatric_age_threshold_months
                    ),
                }
                enriched_records.append(safety_enrichment)
        except Exception as e:
            # If the medication lookup fails (e.g., database offline),
            # we log the error but continue. The Judge will simply not
            # have the safety data and will allow the transaction through.
            logger.warning(
                f"ClinicalSafetyJudge: Could not look up medication "
                f"record for SKU '{sku_id}': {e}"
            )

    # =====================================================================
    # STEP 2: DETERMINISTIC SAFETY CHECK (THE JUDGE)
    # =====================================================================
    # Beginner Note: We run the Rule Engine BEFORE calling Gemini.
    # If the Judge finds a safety violation, we BLOCK the transaction
    # immediately and return a lock message — no LLM call needed.
    # This is the critical difference between Phase 2 and Phase 3:
    #   Phase 2: User query -> Sanitizer -> LLM -> Free-text response
    #   Phase 3: User query -> Sanitizer -> JUDGE -> LLM -> Structured JSON
    #
    # The Judge sits BETWEEN the Sanitizer and the LLM, acting as a
    # deterministic safety gate.
    judge = ClinicalSafetyJudge()
    verdict = judge.evaluate_safety(
        intents=intents,
        retrieved_records=enriched_records,
    )

    # If the Judge says UNSAFE, return immediately with the lock reason.
    # No Gemini call is made — saving money AND preventing the LLM
    # from accidentally contradicting the safety decision.
    if not verdict["is_safe"]:
        lock_reason = verdict["lock_reason"]
        logger.warning(
            f"ClinicalSafetyJudge: Transaction LOCKED. "
            f"Reason: {lock_reason}"
        )

        return {
            "answer": (
                f"SYSTEM LOCK: {lock_reason}. "
                "This medication cannot be dispensed based on the "
                "current patient profile. Consult a senior pharmacist "
                "for manual override."
            ),
            "context_used": context_items,
            "is_safe_to_dispense": False,
            "system_lock_reason": lock_reason,
            "citations": [],
        }

    # =====================================================================
    # STEP 3: HASH-BASED RESULT CACHE CHECK (Phase 4)
    # =====================================================================
    # Beginner Note: Before we do ANY database lookups or AI calls, we
    # check if the EXACT same query has been answered before. We use a
    # two-part cache key:
    #
    #   cache_key = "rag_cache:{SHA256(query)}:{global_db_version}"
    #
    # The SHA256 hashing ensures that even tiny differences in spelling
    # ("paracetamol" vs "paracetomol") produce completely different keys.
    #
    # The global_db_version acts as a cache-buster. When the government
    # scraper updates a drug's safety data (e.g., changing a pregnancy
    # category from B to X), it increments the version. This makes ALL
    # old cache keys invalid because they contain the old version number.
    #
    # Why check the cache BEFORE the DB?
    #   Because the DB search is the most expensive operation (PubMedBERT
    #   vector search + keyword fusion). If we already have the answer,
    #   we skip the DB entirely and return instantly.
    #
    # Exception safety: If Redis is down, get_redis_client() or the
    # cache get/set will raise an exception. We catch it and fall
    # through to the normal pipeline — the cache is an optimization,
    # not a requirement.
    try:
        redis_client = await get_redis_client()
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        version = await get_global_db_version(redis_client)
        cache_key = f"rag_cache:{query_hash}:{version}"

        cached_response = await redis_client.get(cache_key)
        if cached_response is not None:
            logger.info(f"Cache HIT for query hash {query_hash[:12]}... (version {version})")
            # The cached value is a JSON string. We parse it back into a dict.
            return json.loads(cached_response)

        logger.info(
            f"Cache MISS for query hash {query_hash[:12]}... (version {version}). "
            "Proceeding to full pipeline."
        )
    except Exception as cache_error:
        # Redis might be offline. We log the warning and proceed without caching.
        logger.warning(f"Cache check failed (Redis may be offline): {cache_error}")
        redis_client = None
        cache_key = None

    # =====================================================================
    # STEP 4: PROMPT ENGINEERING (WITH JUDGE'S VERDICT INJECTED)
    # =====================================================================
    # Beginner Note: We tell Gemini that the system has already determined
    # the safety status. The AI's job is NOT to decide safety — it's to
    # EXPLAIN why the decision was made, using the clinical context.
    #
    # We also instruct Gemini to return a JSON object that matches our
    # ClinicalNarrativeSchema. This is enforced by the response_schema
    # parameter in generation_config.

    context_blocks = "\n\n".join([f"- {item['content']}" for item in context_items])

    prompt = f"""You are a strict clinical safety narrator for a pharmacy.

The system has determined this transaction is: SAFE — ALLOWED.
You must explain why this medication is safe based on the provided clinical context.

RULES:
1. Do NOT hallucinate or use outside medical knowledge.
2. If the provided context does not contain the answer, set narrative to "INSUFFICIENT CLINICAL DATA. CONSULT PHARMACIST."
3. Keep the narrative concise, professional, and direct.
4. You MUST return a valid JSON object with the following fields:
   - is_safe_to_dispense (boolean): Always true in this context.
   - narrative (string): Your explanation.
   - system_lock_reason (null): Always null in this context.
   - citations (array of strings): Any clinical sources referenced.

CLINICAL CONTEXT:
{context_blocks}

USER QUERY:
{query}
"""

    # =====================================================================
    # STEP 5: CIRCUIT BREAKER + ASYNC GEMINI GENERATION (Phase 4)
    # =====================================================================
    # Beginner Note: This step is the heart of Phase 4's resilience upgrade.
    #
    # We do THREE things differently from Phase 3:
    #
    #   A. CIRCUIT BREAKER: Before calling Gemini, we check if the circuit
    #      breaker is OPEN. If it is, we skip the LLM call entirely and
    #      return the Judge's deterministic verdict immediately (Degraded Mode).
    #
    #   B. ASYNC + TIMEOUT: We use generate_content_async() instead of the
    #      synchronous version, and wrap it in asyncio.wait_for(timeout=5.0).
    #      This prevents the LLM from hanging the API worker for minutes.
    #
    #   C. DEGRADED MODE FALLBACK: If Gemini times out, returns an error, or
    #      the circuit is OPEN, we DO NOT return a 500 error. Instead, we
    #      construct a ClinicalNarrativeSchema using the Judge's verdict and
    #      return it as a "degraded" response. The frontend can display a
    #      banner like "⚠ AI offline — showing deterministic safety rules."
    # =====================================================================
    try:
        # ------------------------------------------------------------------
        # Step 5a: Check the Circuit Breaker
        # ------------------------------------------------------------------
        gemini_cb = get_gemini_circuit_breaker()

        if gemini_cb.current_state == CircuitStateEnum.OPEN:
            # The circuit is open — too many recent failures.
            # Check if enough time has passed to attempt recovery.
            if gemini_cb._should_attempt_recovery():
                logger.info("Gemini circuit HALF-OPEN: attempting recovery.")
                gemini_cb.current_state = CircuitStateEnum.HALF_OPEN
            else:
                # Circuit is OPEN and recovery is not due yet.
                # Skip Gemini entirely and go to degraded mode.
                raise Exception("Circuit breaker is OPEN: Gemini API unavailable")

        # ------------------------------------------------------------------
        # Step 5b: Async Gemini Call with 5-Second Timeout
        # ------------------------------------------------------------------
        model = genai.GenerativeModel('gemini-3.5-flash')

        generation_config = genai.types.GenerationConfig(
            temperature=0.0,
            response_mime_type="application/json",
            response_schema={
                "type": "object",
                "properties": {
                    "is_safe_to_dispense": {"type": "boolean"},
                    "narrative": {"type": "string"},
                    "system_lock_reason": {"type": "string"},
                    "citations": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "is_safe_to_dispense",
                    "narrative",
                    "system_lock_reason",
                    "citations",
                ],
            },
        )

        # Await the async Gemini call with a strict 5-second timeout.
        # If Gemini does not respond within 5 seconds, asyncio.TimeoutError
        # is raised and caught by the except block below.
        response = await asyncio.wait_for(
            model.generate_content_async(prompt, generation_config=generation_config),
            timeout=5.0,
        )

        # Record success in the circuit breaker.
        # This gradually reduces the failure count and eventually closes
        # the circuit if the service has recovered.
        gemini_cb._on_success()

        # ------------------------------------------------------------------
        # Step 5c: Parse & Validate Gemini's JSON Response
        # ------------------------------------------------------------------
        raw_json = response.text.strip()

        # Remove any markdown code block fences that Gemini might add
        if raw_json.startswith("```"):
            raw_json = raw_json.strip("`").strip()
            if raw_json.startswith("json"):
                raw_json = raw_json[4:].strip()

        parsed_data = json.loads(raw_json)
        narrative = ClinicalNarrativeSchema(**parsed_data)

        logger.info(
            f"Clinical Narrator: Gemini returned structured response. "
            f"is_safe_to_dispense={narrative.is_safe_to_dispense}"
        )

        # Build the response dict
        response_data = {
            "answer": narrative.narrative,
            "context_used": context_items,
            "is_safe_to_dispense": narrative.is_safe_to_dispense,
            "system_lock_reason": narrative.system_lock_reason,
            "citations": narrative.citations,
        }

        # ------------------------------------------------------------------
        # Step 5d: Store in Cache (so identical future queries skip Gemini)
        # ------------------------------------------------------------------
        if redis_client is not None and cache_key is not None:
            try:
                await redis_client.set(
                    cache_key,
                    json.dumps(response_data),
                    ex=CACHE_TTL_SECONDS,
                )
                logger.info(f"Cached response for key {cache_key} ({CACHE_TTL_SECONDS}s TTL).")
            except Exception as store_error:
                # Redis might have gone down between our check and store.
                # This is not a fatal error — the response is still valid.
                logger.warning(f"Failed to cache response: {store_error}")

        return response_data

    except Exception as e:
        # =================================================================
        # DEGRADED MODE FALLBACK (Phase 4)
        # =================================================================
        # Beginner Note: ANY failure in the Gemini call (timeout, network
        # error, rate limit, circuit open, JSON parse error) ends up here.
        #
        # In Phase 3, we returned a generic "SYSTEM ERROR" message.
        # In Phase 4, we do something much smarter:
        #
        #   We retrieve the Judge's deterministic verdict (computed in
        #   STEP 2 above) and construct a ClinicalNarrativeSchema from it.
        #
        # This means:
        #   - If the Judge said UNSAFE → fallback says UNSAFE with the
        #     same lock_reason (e.g., CRITICAL_PREGNANCY_CONTRAINDICATION).
        #   - If the Judge said SAFE → fallback says SAFE with a note
        #     that the AI narrative is offline.
        #
        # The pharmacist sees a meaningful response instead of a broken
        # error message. The response even includes the citations field
        # with ["SYSTEM_FALLBACK"] so the frontend can show a yellow
        # warning banner: "⚠ AI offline — showing deterministic rules."
        # =================================================================

        # Record the failure in the circuit breaker (if we got far enough
        # to create one). This increments the failure count and may open
        # the circuit if the threshold is reached.
        try:
            gemini_cb._on_failure()
        except Exception:
            pass  # gemini_cb might not be defined if error was before circuit setup

        # Log the specific error for debugging
        error_type = type(e).__name__
        logger.error(
            f"Clinical Narrator: Gemini call failed ({error_type}: {str(e)}). "
            "Switching to DEGRADED MODE using Judge's verdict."
        )

        # Construct a fallback ClinicalNarrativeSchema from the Judge's
        # deterministic verdict. This is the key insight of Phase 4:
        # we NEVER lose the safety decision, even when the LLM is down.
        fallback_narrative = ClinicalNarrativeSchema(
            is_safe_to_dispense=verdict["is_safe"],
            narrative=(
                "NETWORK TIMEOUT: AI Narrative offline. "
                "Deterministic safety rules applied."
            ),
            system_lock_reason=verdict["lock_reason"],
            citations=["SYSTEM_FALLBACK"],
        )

        return {
            "answer": fallback_narrative.narrative,
            "context_used": context_items,
            "is_safe_to_dispense": fallback_narrative.is_safe_to_dispense,
            "system_lock_reason": fallback_narrative.system_lock_reason,
            "citations": fallback_narrative.citations,
        }
