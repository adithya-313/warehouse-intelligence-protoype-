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
from app.infrastructure.models import (
    MedicationBatchModel,
    MedicationModel,
    ClinicalKnowledgeBase,
)
from app.services.rule_engine import ClinicalSafetyJudge
from app.services.fefo_engine import get_optimal_fefo_batch
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
#
# IMPORTANT: This is imported from the canonical source in app.domain.
# If you need to add a keyword, add it to app/domain/intent_keywords.py.
from app.domain.intent_keywords import OBJECTIVE_KEYWORDS as OBJECTIVE_KEYWORDS_LIST


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
    # We try three patterns:
    #   1. Standard format with hyphen (e.g., "AMOXI-500", "PAN-40").
    #   2. No separator (e.g., "PAN40", "DOLO650").
    #   3. Space between brand name and strength (e.g., "calpol 650",
    #      "pan 40", "augmentin 625") — common in conversational queries.
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
            # Pattern 2: "PAN40", "AMOXI500", "dolo650" (no separator)
            sku_match = re.search(r"([A-Z]+)(\d+)", query, re.IGNORECASE)
            if sku_match:
                sku_id = f"{sku_match.group(1).upper()}-{sku_match.group(2)}"
                logger.info(
                    f"Adaptive Router: Extracted SKU '{sku_id}' from query "
                    f"(no-hyphen pattern — hyphen inserted)."
                )
        # Pattern 3: "calpol 650", "augmentin 625", "pan 40" (space between
        # brand letters and strength digits). We strip the space and keep
        # the bare code (no hyphen) since the DB stores bare codes.
        if sku_id is None:
            sku_match = re.search(r"([A-Z]+)\s+(\d+)", query, re.IGNORECASE)
            if sku_match:
                sku_id = f"{sku_match.group(1).upper()}{sku_match.group(2)}"
                logger.info(
                    f"Adaptive Router: Extracted SKU '{sku_id}' from query "
                    f"(space-separated pattern — bare code)."
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
        #
        # Normalize: Try both hyphenated and bare-code formats since the
        # DB stores bare codes (e.g., "CALPOL650") but Patterns 1 and 2
        # produce hyphenated codes (e.g., "CALPOL-650"). Pattern 3
        # produces bare codes. We try both to ensure a match.
        sku_variants = {sku_id, sku_id.replace("-", "")}
        medication_batches = db.query(MedicationBatchModel).filter(
            MedicationBatchModel.sku_id.in_(sku_variants)
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
                "path_taken": "inventory",
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
                "path_taken": "inventory",
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

    clinical_result = await generate_clinical_response(
        db=db,
        query=query,
        sku_id=sku_id,
        intents=intents or {},
    )
    
    # We tag the result here so the endpoint knows which path was taken, 
    # without needing to change the clinical function itself.
    clinical_result["path_taken"] = "clinical"
    return clinical_result


# =====================================================================
# LEXICAL ENTITY EXTRACTION — DIRECT DRUG LOOKUP BYPASS (Phase 10)
# =====================================================================
# Beginner Note: Long conversational queries like "Can I give half a
# PAN40 to a 3-year-old?" dilute the vector embedding (the sentence
# is mostly filler words like "can", "I", "give", "half", "to", "a").
# The vector score drops below 0.60, and the FTS (plainto_tsquery)
# strips stop words so aggressively that the drug name is the only
# meaningful token left — which still may not match because FTS
# tokenizes "PAN40" as an unknown word and discards it.
#
# This function is a pre-retrieval safety net:
#   1. Query the database for ALL known drug identifiers (SKU codes,
#      brand names, generic names).
#   2. Scan the user's raw query string (case-insensitive) for any of
#      these identifiers as substrings.
#   3. If a match is found, perform a DIRECT hard SQL lookup on
#      clinical_knowledge_base for that drug's full clinical record.
#   4. Return the matched record(s) so the caller can inject them into
#      the Judge's enriched_records BEFORE the vector search results.
#
# This guarantees that even when vector similarity fails due to query
# dilution, the ClinicalSafetyJudge still evaluates the CORRECT drug's
# safety data.


def get_known_drug_catalog(db: Session) -> tuple[set[str], set[str]]:
    """
    Fetch all known identifiers from the database.
    We collect SKU IDs (e.g., "PAN40", "TELMA40") from the medications
    table AND brand names + generic names from the clinical knowledge
    metadata payload. These are our "catalog" of known entities.
    
    Beginner Note:
        This is separated out so that both exact matching (extract_known_entities)
        and fuzzy matching (resolve_drug_entity) can share the same database
        lookups without duplicating the queries.
        
    Returns:
        A tuple of (known_skus, known_brands) where both sets are in UPPERCASE.
    """
    try:
        # Fetch all SKU IDs from the medications table
        sku_rows = (
            db.query(MedicationModel.sku_id)
            .all()
        )
        known_skus: set[str] = {row.sku_id.upper() for row in sku_rows if row.sku_id}

        # Fetch brand names and generic names from clinical knowledge
        # metadata. The metadata_payload column is a JSONB dict that
        # typically contains keys like 'brand_name', 'generic_name',
        # 'therapeutic_class', etc.
        brand_rows = (
            db.query(
                ClinicalKnowledgeBase.metadata_payload
            )
            .all()
        )
        known_brands: set[str] = set()
        for row in brand_rows:
            payload = row.metadata_payload or {}
            if isinstance(payload, dict):
                brand = payload.get("brand_name", "")
                generic = payload.get("generic_name", "")
                if brand:
                    known_brands.add(brand.upper())
                if generic:
                    known_brands.add(generic.upper())
                    
        return known_skus, known_brands
    except Exception as e:
        logger.warning(
            f"Entity Extraction: Could not load known identifiers: {e}"
        )
        return set(), set()


def extract_known_entities(
    db: Session,
    query: str,
) -> list[dict]:
    """
    Scan the query for known drug identifiers and return matching
    clinical knowledge records via direct SQL lookup.

    Parameters:
        db: Active database session.
        query: The user's raw query string.

    Returns:
        A list of dicts, each with keys 'sku_id' and 'content'
        (matching the format of vector search results so they can be
        merged seamlessly). Returns an empty list if no entities found.
    """
    # Step 1: Fetch all known identifiers from the database.
    known_skus, known_brands = get_known_drug_catalog(db)
    
    if not known_skus and not known_brands:
        return []

    # Step 2: Scan the query for each known identifier.
    # We check every identifier as a case-insensitive substring of
    # the query. We prefer LONGER matches over shorter ones to avoid
    # false positives (e.g., "PAN" matching inside "PANTROPRAZOLE").
    query_upper = query.upper()
    matched_entities: list[str] = []

    for sku in known_skus:
        if sku.upper() in query_upper:
            matched_entities.append(sku)

    for brand in known_brands:
        if brand in query_upper:
            matched_entities.append(brand)

    # Scan for tokens matching the alias table
    import re
    from sqlalchemy import text
    from app.domain.drug_resolver import normalize_drug_name
    
    tokens = re.findall(r"(?i)\b([a-z0-9-]{3,})\b", query)
    stop_words = {"TELL", "ME", "ABOUT", "WHAT", "IS", "THE", "OF", "FOR", "AND", "WITH"}
    for token in tokens:
        if token.upper() in stop_words:
            continue
            
        token_clean = token.upper().replace("-", "")
        alias_candidates_sql = text("""
            SELECT sku_id, alias_text 
            FROM drug_brand_aliases 
            WHERE REPLACE(alias_text, ' ', '') ILIKE :prefix 
            LIMIT 50
        """)
        candidates = db.execute(alias_candidates_sql, {"prefix": f"{token_clean}%"}).fetchall()
        normalized_token = normalize_drug_name(token)
        for cand_sku, cand_alias in candidates:
            if normalize_drug_name(cand_alias) == normalized_token:
                logger.info(f"Entity Extraction: Token '{token}' matched alias '{cand_alias}' -> '{cand_sku}'")
                matched_entities.append(cand_sku)
                break

    # Remove duplicates and sort by length descending (longest match
    # first — the most specific identifier wins).
    matched_entities = sorted(
        set(matched_entities),
        key=len,
        reverse=True,
    )

    if not matched_entities:
        logger.info(
            "Entity Extraction: No known drug identifiers found in query."
        )
        return []

    logger.info(
        f"Entity Extraction: Found {len(matched_entities)} identifiers "
        f"in query: {matched_entities}"
    )

    # Step 3: Do a direct SQL lookup on clinical_knowledge_base for
    # each matched entity. We query by sku_id (the primary identifier),
    # but we also check the metadata_payload for brand_name/generic_name
    # matches.
    results: list[dict] = []
    seen_sku_ids: set[str] = set()

    for entity in matched_entities:
        try:
            # First try matching as an SKU ID
            kb_record = (
                db.query(ClinicalKnowledgeBase)
                .filter(
                    ClinicalKnowledgeBase.sku_id == entity.replace("-", "")
                )
                .first()
            )

            # Fallback: if no direct SKU match, try matching the entity against
            # the JSON metadata payload (generic_name or brand_name). This handles
            # cases where the matched entity was a plain name (e.g. "NIMESULIDE")
            # but the real SKU is something like "GENERIC_REF_NIMESULIDE".
            if not kb_record:
                from sqlalchemy import text
                fallback_sql = text("""
                    SELECT sku_id 
                    FROM clinical_knowledge_base 
                    WHERE metadata_payload->>'generic_name' ILIKE :entity 
                       OR metadata_payload->>'brand_name' ILIKE :entity 
                    LIMIT 1
                """)
                fallback_result = db.execute(fallback_sql, {"entity": entity}).fetchone()
                if fallback_result:
                    fallback_sku = fallback_result[0]
                    kb_record = db.query(ClinicalKnowledgeBase).filter(ClinicalKnowledgeBase.sku_id == fallback_sku).first()
                    logger.info(
                        f"Entity Extraction: Fallback matched name '{entity}' "
                        f"to SKU '{fallback_sku}'."
                    )

            if kb_record and kb_record.sku_id not in seen_sku_ids:
                seen_sku_ids.add(kb_record.sku_id)
                results.append({
                    "sku_id": kb_record.sku_id,
                    "content": kb_record.content,
                    "confidence_score": 1.0,
                    "metadata_payload": kb_record.metadata_payload,
                })
                logger.info(
                    f"Entity Extraction: Direct lookup found clinical "
                    f"record for SKU '{kb_record.sku_id}'."
                )
        except Exception as e:
            logger.warning(
                f"Entity Extraction: Lookup failed for '{entity}': {e}"
            )

    if len(seen_sku_ids) > 1:
        logger.info(f"Entity Extraction: Found {len(seen_sku_ids)} distinct SKUs. Triggering disambiguation.")
        choices = []
        for r in results:
            payload = r.get("metadata_payload") or {}
            display_name = payload.get("generic_name") or payload.get("brand_name") or r["sku_id"]
            choices.append({
                "sku_id": r["sku_id"],
                "display_name": display_name
            })
        return {
            "status": "disambiguate",
            "choices": choices
        }

    return results


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
        from google import genai as _genai
        from google.genai import types as _genai_types
        settings = get_application_settings()
        if not settings.GEMINI_API_KEY:
            logger.warning("GEMINI_API_KEY is missing. RAG pipeline will fail if called.")
        gemini_client = _genai.Client(api_key=settings.GEMINI_API_KEY)
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
    # STEP 1: PRE-RETRIEVAL ENTITY EXTRACTION (Phase 10)
    # =====================================================================
    # Beginner Note: Before we run the vector search (which can fail on
    # long conversational queries due to vector dilution), we do a
    # direct LEXICAL scan of the query against all known drug identifiers
    # in the database. If we find a match, we pre-load the clinical
    # knowledge record so the Judge will definitely see it.
    #
    # This runs BEFORE the vector search so that even if the vector
    # search returns empty or low-confidence results, the direct
    # lookup records are already captured and injected into
    # enriched_records for the Judge to evaluate.
    direct_lookup_records = extract_known_entities(
        db=db,
        query=query,
    )
    if isinstance(direct_lookup_records, dict) and direct_lookup_records.get("status") == "disambiguate":
        return direct_lookup_records

    # If we found a direct match, also update the sku_id for better
    # vector search filtering (this helps the vector search narrow down
    # to the right drug even with a diluted query).
    if direct_lookup_records and sku_id is None:
        sku_id = direct_lookup_records[0]["sku_id"]
        logger.info(
            f"Entity Extraction: Updated sku_id to '{sku_id}' "
            f"from direct lookup."
        )

    # =====================================================================
    # STEP 2: VECTOR + KEYWORD HYBRID SEARCH
    # =====================================================================
    # We query the vector database for the top 3 most relevant clinical
    # guidelines. Lazy import: Only load sentence_transformers when
    # clinical RAG is actually needed.
    from app.services.semantic_search import execute_clinical_search
    search_results = execute_clinical_search(db=db, query=query, sku_id=sku_id, top_k=3)
    context_items = search_results["results"]

    # DIAG-5.3: log the raw list of records returned by retrieval
    _diag_records = []
    for r in context_items:
        meta = r.get("metadata_payload") or {}
        _diag_records.append({
            "sku_id": r.get("sku_id"),
            "generic_name": meta.get("generic_name"),
            "is_approved_by_curator": meta.get("is_approved_by_curator"),
            "clinical_fields_is_null": not bool(r.get("content")),
            "confidence_score": r.get("confidence_score")
        })
    logger.info(f"[DIAG-5.3] RAW RETRIEVAL RESULTS: {_diag_records}")

    # Merge direct lookup records with vector search results.
    # We combine them first, then deduplicate by sku_id to ensure we only
    # keep one copy of each unique medication record.
    all_combined_records = context_items + direct_lookup_records
    deduped_context_items = {}
    duplicates_removed = 0

    for record in all_combined_records:
        sku = record.get("sku_id")
        if not sku:
            continue
            
        if sku not in deduped_context_items:
            deduped_context_items[sku] = record
        else:
            duplicates_removed += 1
            # If the same SKU was returned by both paths, we need to choose the best one.
            # We prefer the record that is more complete (has more content) over an incomplete one.
            existing_record = deduped_context_items[sku]
            existing_content_len = len(existing_record.get("content") or "")
            new_content_len = len(record.get("content") or "")
            
            if new_content_len > existing_content_len:
                deduped_context_items[sku] = record
                
    if duplicates_removed > 0:
        logger.info(f"Context Assembly: Removed {duplicates_removed} duplicate records during deduplication.")
        
    # Replace the context_items list with our fully deduplicated set
    context_items = list(deduped_context_items.values())

    # =====================================================================
    # STEP 3: ENRICH RETRIEVED RECORDS WITH MEDICATION SAFETY DATA
    # =====================================================================
    # Beginner Note: The clinical_search returns records from the
    # clinical_knowledge_base table, which does NOT contain pregnancy
    # categories or pediatric age thresholds. Those live in the
    # medications table. We look up the medication record here and
    # add its safety fields to the retrieved records so the Judge
    # has all the data it needs.
    enriched_records = list(context_items)

    # Look up each retrieved record's medication safety data so the Judge
    # can inspect pregnancy_category, pediatric_age_threshold_months, etc.
    for ctx_item in context_items:
        ctx_sku = ctx_item.get("sku_id")
        if not ctx_sku:
            continue
        try:
            # Normalize: try both hyphenated and de-hyphenated SKU formats
            # since extraction may add hyphens but the DB stores bare codes.
            sku_variants = {ctx_sku, ctx_sku.replace("-", "")}
            med_record = (
                db.query(MedicationModel)
                .filter(MedicationModel.sku_id.in_(sku_variants))
                .first()
            )
            if med_record:
                ctx_item["pregnancy_category"] = med_record.pregnancy_category
                ctx_item["pediatric_age_threshold_months"] = (
                    med_record.pediatric_age_threshold_months
                )
        except Exception as e:
            logger.warning(
                f"ClinicalSafetyJudge: Could not look up medication "
                f"record for SKU '{ctx_sku}': {e}"
            )

        # Beginner Note: We also need to know if the pharmacy actually has this
        # medication in stock right now, so Gemini can tell the patient. We reuse
        # the exact same FEFO (First-Expire-First-Out) logic the checkout system
        # trusts so we don't hallucinate inventory.
        try:
            batch = get_optimal_fefo_batch(db, ctx_sku, required_qty=1)
            if batch:
                ctx_item["stock_qty"] = batch["available_quantity"]
                ctx_item["unit_price"] = batch["max_retail_price"]
                ctx_item["expiry_date"] = batch["expiry_date"].isoformat()
                logger.info(f"Stock enrichment: SKU={ctx_sku}, qty={ctx_item['stock_qty']}, price={ctx_item['unit_price']} — attached to context")
            else:
                logger.info(f"Stock enrichment: SKU={ctx_sku} — no stock data found, skipped")
        except Exception as e:
            logger.warning(f"Stock enrichment: Could not look up stock for SKU '{ctx_sku}': {e}")

    # Fallback: If no records were found by search but we have a SKU,
    # do a direct medication lookup so the Judge still has safety data
    # to evaluate. This prevents Category X/D drugs from slipping through
    # when vector similarity fails due to query dilution.
    if not enriched_records and sku_id:
        try:
            # Normalize: Try both hyphenated and de-hyphenated formats.
            # Some SKUs are stored as "RISO20" in the DB but extracted as
            # "RISO-20" from query text. We try both.
            sku_variants = {sku_id, sku_id.replace("-", "")}
            med_record = (
                db.query(MedicationModel)
                .filter(MedicationModel.sku_id.in_(sku_variants))
                .first()
            )
            if med_record:
                safe_sku = med_record.sku_id
                enriched_records.append({
                    "sku_id": safe_sku,
                    "pregnancy_category": med_record.pregnancy_category,
                    "pediatric_age_threshold_months": (
                        med_record.pediatric_age_threshold_months
                    ),
                })
                logger.info(
                    f"SKU Fallback: Direct medication lookup for "
                    f"{sku_id}/{safe_sku} enriched the Judge with "
                    f"safety data "
                    f"(preg_category={med_record.pregnancy_category})."
                )
        except Exception as e:
            logger.warning(f"SKU Fallback: Could not look up SKU '{sku_id}': {e}")

    # =====================================================================
    # STEP 4: DETERMINISTIC SAFETY CHECK (THE JUDGE) — BEFORE THRESHOLD GATE
    # =====================================================================
    # Beginner Note: The Judge MUST run BEFORE the confidence-threshold
    # early exit. Even if the vector search returned low-confidence
    # results, the Judge must evaluate pregnancy/pediatric intents.
    # This prevents the "safety dilution" bug where safety-language words
    # in the query ("safety", "safe") drop vector similarity below the
    # threshold, causing the Judge to never see the medication records.
    #
    # The Judge sits BETWEEN the Sanitizer and the LLM, acting as a
    # deterministic safety gate. If it blocks, we return immediately
    # and skip both the safety-warning response AND the LLM call.
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
            "question_type": "safety_check",
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
    # STEP 4.5: EARLY EXIT IF BOTH VECTOR SEARCH AND ENTITY EXTRACTION
    #           FOUND NOTHING
    # =====================================================================
    # Beginner Note: If BOTH the vector search AND the entity extraction
    # returned zero results, AND the Judge did not block the transaction,
    # we return a graceful safety-warning message. The entity extraction
    # bypass injects records with confidence_score=1.0, so if it found
    # anything, context_items will be non-empty even when the vector
    # search failed. We only exit early when NEITHER method found data.
    if search_results.get("safety_warning") and not direct_lookup_records:
        return {
            "question_type": "safety_check",
            "answer": search_results["safety_warning"],
            "context_used": [],
            "is_safe_to_dispense": True,
            "system_lock_reason": None,
            "citations": [],
        }

    # =====================================================================
    # STEP 5: HASH-BASED RESULT CACHE CHECK (Phase 4)
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
    # STEP 6: PROMPT ENGINEERING (WITH JUDGE'S VERDICT INJECTED)
    # =====================================================================
    # Beginner Note: We tell Gemini that the system has already determined
    # the safety status. The AI's job is NOT to decide safety — it's to
    # EXPLAIN why the decision was made, using the clinical context.
    #
    # We also instruct Gemini to return a JSON object that matches our
    # ClinicalNarrativeSchema. This is enforced by the response_schema
    # parameter in generation_config.

    # Beginner Note: We build the context list as a string. If the enrichment
    # loop found stock data for an item, we inject it directly into the line
    # so Gemini can see the exact real-time inventory and price.
    rendered_blocks = []
    for item in context_items:
        base_text = f"- {item['content']}"
        if "stock_qty" in item and "unit_price" in item and "expiry_date" in item:
            base_text += f" (In stock: {item['stock_qty']} units, ₹{item['unit_price']}, expires {item['expiry_date']})"
        rendered_blocks.append(base_text)
    
    context_blocks = "\n\n".join(rendered_blocks)

    # Beginner Note: By this point the Judge has already run and determined
    # the safety of the transaction. We pass its verdict into the prompt so the
    # LLM can include it if the user is asking about safety.
    judge_verdict_str = "SAFE — ALLOWED" if verdict.get("is_safe", True) else f"UNSAFE — BLOCKED (Rule: {verdict.get('triggered_rule')})"
    
    # Beginner Note: Check if this is a symptom/side-effect question for a drug
    # that doesn't have a distinct 'Adverse Reactions' section. If so, tell the LLM
    # to check the 'Warnings' section instead before giving up.
    query_lower = query.lower()
    is_symptom_query = "symptom" in query_lower or "side effect" in query_lower
    has_adverse_reactions = "adverse reactions" in context_blocks.lower()
    
    symptom_instruction = ""
    if is_symptom_query and not has_adverse_reactions:
        symptom_instruction = (
            "\n\nIMPORTANT: For this drug, side-effect and symptom information may "
            "be included within the Warnings section rather than a separate Adverse "
            "Reactions section — check there before saying the information isn't available."
        )

    prompt = f"""You are a clinical assistant helping a pharmacist. Answer the pharmacist's
actual question using ONLY the clinical context provided below. Do not use
outside medical knowledge.

First, identify what kind of question this is: one of
"symptom", "dosage", "comparison", "general_info", or "safety_check".

Then answer that question directly and clearly, using the clinical context.{symptom_instruction}

Separately, the system has already checked this specific transaction for
dispensing safety: {judge_verdict_str}. If the pharmacist's
question is about safety or dispensing, include this in your answer. If
their question is about something else (like symptoms or a comparison),
you do not need to mention dispensing safety at all — just answer their
real question.

If the clinical context does not contain enough information to answer
the specific question asked, say so honestly and specifically — name what
information is missing, rather than giving a generic refusal.

OUTPUT RULES:
1. system_lock_reason: If the transaction is SAFE, this field MUST be exactly null (not a string, not an empty string). If the transaction is BLOCKED, this field must contain the exact reason code (e.g. "CRITICAL_PREGNANCY_CONTRAINDICATION").
2. citations: This must only contain actual named clinical sources from the context.
   - CORRECT: ["OpenFDA monograph", "FDA label", "CDSCO Guidelines"]
   - INCORRECT: ["Indications: GERD", "SAFE — ALLOWED", "Contraindications: Severe liver disease"]
   Never include paraphrased text or the safety verdict in citations.

CLINICAL CONTEXT:
{context_blocks}

USER QUESTION:
{query}
"""

    # DIAG-5.3: capturing exactly what the LLM was told to do
    logger.info(f"[DIAG-5.3] FULL PROMPT SENT TO LLM:\n{prompt}")

    # =====================================================================
    # STEP 7: CIRCUIT BREAKER + ASYNC GEMINI GENERATION (Phase 4)
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
        # ---------------------------------------------------------------
        # Modern google-genai SDK: synchronous Client.models.generate_content
        # run in a thread pool so we don't block the event loop.
        # Timeout raised to 30s — the new SDK connects faster (HTTP/2)
        # but Gemini 2.5-flash may take a few seconds to warm up.
        # ---------------------------------------------------------------
        generation_config = _genai_types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
            response_schema={
                "type": "object",
                "properties": {
                    "question_type": {"type": "string"},
                    "is_safe_to_dispense": {"type": "boolean"},
                    "narrative": {"type": "string"},
                    "system_lock_reason": {"type": "string"},
                    "citations": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "question_type",
                    "is_safe_to_dispense",
                    "narrative",
                    "system_lock_reason",
                    "citations",
                ],
            },
        )

        # Run the synchronous SDK call in a thread pool so it doesn't
        # block the FastAPI async event loop. Timeout is 30 seconds.
        response = await asyncio.wait_for(
            asyncio.to_thread(
                gemini_client.models.generate_content,
                model="gemini-flash-lite-latest",
                contents=prompt,
                config=generation_config,
            ),
            timeout=30.0,
        )

        # Record success in the circuit breaker.
        # This gradually reduces the failure count and eventually closes
        # the circuit if the service has recovered.
        gemini_cb._on_success()

        # ------------------------------------------------------------------
        # Step 5c: Parse & Validate Gemini's JSON Response
        # ------------------------------------------------------------------
        raw_json = response.text.strip()
        
        # DIAG-5.3: capturing raw LLM response text before any post-processing
        logger.info(f"[DIAG-5.3] RAW LLM RESPONSE:\n{raw_json}")

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
            "question_type": narrative.question_type,
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
        #   STEP 4 above) and construct a ClinicalNarrativeSchema from it.
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
            question_type="safety_check",
            is_safe_to_dispense=verdict["is_safe"],
            narrative=(
                "NETWORK TIMEOUT: AI Narrative offline. "
                "Deterministic safety rules applied."
            ),
            system_lock_reason=verdict["lock_reason"],
            citations=["SYSTEM_FALLBACK"],
        )

        return {
            "question_type": fallback_narrative.question_type,
            "answer": fallback_narrative.narrative,
            "context_used": context_items,
            "is_safe_to_dispense": fallback_narrative.is_safe_to_dispense,
            "system_lock_reason": fallback_narrative.system_lock_reason,
            "citations": fallback_narrative.citations,
        }

