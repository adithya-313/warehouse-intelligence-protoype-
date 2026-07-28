import uuid
import time
import logging
from fastapi import APIRouter, status, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.infrastructure.database import get_database_session
from app.domain.schemas import KnowledgeIngestionRequest, KnowledgeIngestionResponse, SemanticSearchRequest, SemanticSearchResponse, RAGQueryRequest, RAGQueryResponse, SubstituteRequestSchema, SubstituteResponseSchema, SubstituteItemSchema
from app.domain.drug_resolver import resolve_drug_entity
from app.workers.embedding_tasks import generate_and_store_embedding
from app.services.semantic_search import execute_clinical_search, find_clinical_substitutes
from app.services.rag_pipeline import route_and_process_query
from app.services.sanitizer import QuerySanitizer
from app.domain.intent import IntentBucket
from app.domain.intent_gate import classify_intent

logger = logging.getLogger(__name__)

# Create a single reusable instance of the QuerySanitizer.
# Beginner Note: We create this at MODULE LEVEL so that the sanitizer
# is instantiated once when the application starts and reused for every
# request. There is no per-request state to reset, so a single instance
# is safe and efficient.
sanitizer = QuerySanitizer()

router = APIRouter()

@router.post("/ingest", response_model=KnowledgeIngestionResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_clinical_knowledge(payload: KnowledgeIngestionRequest):
    """
    Ingest clinical guidelines. 
    Returns 202 Accepted instantly and processes the AI embedding in the background.
    """
    # Dispatch to Celery
    task = generate_and_store_embedding.delay(
        sku_id=payload.sku_id,
        content=payload.content,
        metadata=payload.metadata_payload
    )

    return KnowledgeIngestionResponse(
        message="Clinical knowledge queued for vector embedding.",
        task_id=task.id
    )

@router.post("/search", response_model=SemanticSearchResponse, status_code=status.HTTP_200_OK)
async def search_clinical_knowledge(
    payload: SemanticSearchRequest,
    db: Session = Depends(get_database_session)
):
    """
    Semantic Search Endpoint.
    Allows junior staff to ask clinical questions in plain English.
    Enforces strict confidence thresholds to prevent medical hallucinations.
    """
    search_data = execute_clinical_search(
        db=db,
        query=payload.query,
        sku_id=payload.sku_id,
        top_k=payload.top_k
    )

    return SemanticSearchResponse(
        query=payload.query,
        results=search_data["results"],
        safety_warning=search_data["safety_warning"]
    )

@router.post("/ask", response_model=RAGQueryResponse, status_code=status.HTTP_200_OK)
async def ask_clinical_assistant(
    payload: RAGQueryRequest,
    db: Session = Depends(get_database_session)
):
    """
    Adaptive AI Assistant Endpoint.
    Routes each query through the Adaptive Routing system:
      - Objective queries (price, stock, MRP) → answered from database instantly.
      - Substitute queries → answered from the substitute finder (vector + inventory).
      - Clinical/subjective queries → answered via Gemini RAG with clinical context.

    Beginner Note:
        Before any routing happens, the query passes through the QuerySanitizer
        which handles THREE preprocessing steps:
          1. clean_drug_names() — fixes misspellings using fuzzy matching.
          2. extract_sku() — finds drug SKU codes anywhere in the query.
          3. extract_intents() — identifies what the user wants (pregnancy
             safety, pediatric dosage, substitute, or simple objective data).
    """

    import uuid
    import time

    correlation_id = str(uuid.uuid4())
    start_time = time.monotonic()
    
    # This dict collects facts about this one request as we go, so we can log exactly
    # one clean summary line at the very end, no matter which exit door the request leaves through.
    request_metrics = {
        "intent": None,
        "path_taken": None,
        "fallback_triggered": False,
        "drug_resolved": None,
        "disambiguation_triggered": False,
    }
    
    try:
        # =====================================================================
        # STEP 0: SANITIZE THE QUERY
        # =====================================================================
        # Beginner Note: We build a list of valid drug names from the frontend
        # payload (if a specific SKU was provided) or from the query text
        # itself. The sanitizer will check each word against this list and
        # correct any close misspellings (60% similarity threshold).

        # Start with the query text as-is
        raw_query = payload.query

        # Build a list of valid drug names to check against.
        # If the frontend provided a SKU, include it so the user's
        # misspelling of that SKU gets corrected.
        valid_names_list = []
        if payload.sku_id:
            valid_names_list.append(payload.sku_id)

        # Run the fuzzy drug-name cleaner on the query.
        # This replaces words like "Crooosin" with "CROCIN" so the
        # search engine receives a correctly-spelled query.
        cleaned_query = sanitizer.clean_drug_names(
            query=raw_query,
            valid_names=valid_names_list,
        )

        # Extract the SKU from the cleaned query text using the unified
        # regex pattern (handles both "AMOXI-500" and "PAN40" formats).
        extracted_sku = sanitizer.extract_sku(cleaned_query)

        # Determine which intents are present in the query.
        intents = sanitizer.extract_intents(cleaned_query)

        # =====================================================================
        # STEP 1: INTENT GATE — TRAFFIC COP (Phase 1)
        # =====================================================================
        # Beginner Note: Before we do ANY database work, we classify the query
        # into one of four buckets using only the query text and the extracted
        # SKU. This is a pure function — no I/O, no DB, no vector search.
        #
        # The gate checks:
        #   - Is there a drug (SKU) in the query? (cheap regex only)
        #   - Is there an objective keyword ("price", "stock", etc.)?
        #
        # If NEITHER: NO_INTENT → return "please rephrase" immediately.
        #   Zero DB calls, zero vector calls, zero LLM calls.
        #
        # If drug + keyword: INVENTORY → proceed to database path.
        #   (Phase 3 will enhance this with SQL stock injection.)
        #
        # If drug but no keyword: AMBIGUOUS → proceed to clinical path.
        #   (The existing pregnancy/pediatric/substitute checks further
        #   downstream will resolve this to CLINICAL if a clinical keyword
        #   is found. All other ambiguous queries default to the RAG pipeline,
        #   which is the safe fail-safe.)
        bucket = classify_intent(
            query=cleaned_query,
            sku_id=extracted_sku,
            has_objective_keyword=intents["objective"],
        )

        # TEMP: minimal trace log for Phase 1 verification — Phase 4 will replace
        # this with structured JSON covering the full funnel decision.
        logger.info(
            f"IntentGate decision: bucket={bucket.value} "
            f"sku_id={extracted_sku} "
            f"query_len={len(cleaned_query)}"
        )

        # =====================================================================
        # PHASE 2: DRUG ENTITY RESOLVER (Disambiguation)
        # =====================================================================
        # Pass the known SKU if we already have it from the frontend.
        # (extracted_sku is also populated here, but it's generated by a regex
        # and may introduce hyphenation mismatches like "PN-40" instead of "PN40").
        known_sku = payload.sku_id
        
        # Fix A: We ALWAYS run the resolver first so we can rescue queries that
        # contain a generic/brand name but no explicit regex SKU or intents
        # (e.g. "is amoxycillin safe with alcohol").
        resolution = resolve_drug_entity(db, cleaned_query, sku_id=known_sku)

        if bucket == IntentBucket.NO_INTENT:
            # If the regex found no drug, but the DB catalog resolver DID find one
            # (either exact brand match or fuzzy), we rescue the query!
            if resolution["status"] in ("resolved", "disambiguate"):
                logger.info("IntentGate rescued by DrugResolver: Found catalog match despite no regex SKU.")
                if intents["objective"]:
                    bucket = IntentBucket.INVENTORY
                else:
                    bucket = IntentBucket.AMBIGUOUS
            else:
                # ------------------------------------------------------------------
                # FINAL FAIL-SAFE: No regex drug AND no catalog match.
                # ------------------------------------------------------------------
                # If there are NO intents (e.g. "what's the weather today"), treat as NO_INTENT.
                if not any(intents.values()):
                    request_metrics["intent"] = bucket.value if hasattr(bucket, "value") else str(bucket)
                    request_metrics["path_taken"] = "none"
                    request_metrics["fallback_triggered"] = True
                    return RAGQueryResponse(
                        query=payload.query,
                        answer=(
                            "I could not identify a specific medication in your query. "
                            "Please include the medication name (e.g., 'PAN-40', "
                            "'TELMA-40', 'calpol 650'). If you need clinical advice, "
                            "ask with a drug name included."
                        ),
                        context_used=[],
                        is_safe_to_dispense=True,
                        system_lock_reason=None,
                        citations=[],
                        status="no_intent"
                    )
                # If there ARE intents but no drug (e.g. "is it safe for pregnancy?"), let it fall through 
                # to the "no_match" handler below.

        # Now handle the resolver's short-circuits (no_match and disambiguate)
        if resolution["status"] == "no_match":
            request_metrics["intent"] = bucket.value if hasattr(bucket, "value") else str(bucket)
            request_metrics["drug_resolved"] = False
            request_metrics["disambiguation_triggered"] = False
            request_metrics["fallback_triggered"] = True
            request_metrics["path_taken"] = "none"
            return RAGQueryResponse(
                query=payload.query,
                answer=(
                    "I could not find a match for that medication in our catalog. "
                    "Please check the spelling and try again."
                ),
                context_used=[],
                is_safe_to_dispense=True,
                system_lock_reason=None,
                citations=[],
                status="no_match"
            )
        elif resolution["status"] == "disambiguate":
            # Fix 3: Display name lookup for disambiguation choices
            # We look up a clean, human-readable display name for each sku_id.
            # We check clinical_knowledge_base for generics, and medications for brands.
            display_choices = []
            for sku in resolution["choices"]:
                display_name = None
                
                # Check generics first
                if sku.startswith("GENERIC_REF_"):
                    # Fast SQL to grab the generic_name from JSONB metadata_payload
                    name_query = text("""
                        SELECT metadata_payload->>'generic_name' 
                        FROM clinical_knowledge_base 
                        WHERE sku_id = :sku
                    """)
                    result = db.execute(name_query, {"sku": sku}).scalar()
                    if result:
                        display_name = result
                else:
                    # Check medications table for brands
                    name_query = text("""
                        SELECT apis[1] 
                        FROM medications 
                        WHERE sku_id = :sku
                    """)
                    result = db.execute(name_query, {"sku": sku}).scalar()
                    if result:
                        display_name = result
                
                # Fallback if no name found
                if not display_name:
                    if sku.startswith("GENERIC_REF_"):
                        display_name = sku.replace("GENERIC_REF_", "").replace("_", " ").title()
                    else:
                        display_name = sku
                
                display_choices.append({
                    "sku_id": sku,
                    "display_name": display_name
                })
                
            request_metrics["intent"] = bucket.value if hasattr(bucket, "value") else str(bucket)
            request_metrics["drug_resolved"] = False
            request_metrics["disambiguation_triggered"] = True
            request_metrics["path_taken"] = "none"
            return RAGQueryResponse(
                query=payload.query,
                answer="I found multiple matches. Did you mean one of these?",
                context_used=[],
                is_safe_to_dispense=True,
                system_lock_reason=None,
                citations=[],
                status="disambiguate",
                choices=display_choices
            )
        elif resolution["status"] == "resolved":
            extracted_sku = resolution["sku_id"]
        elif resolution["status"] == "multi_drug_resolved":
            logger.info(f"Multi-drug intent confirmed, passing {len(resolution['sku_ids'])} drugs to RAG pipeline without disambiguation.")
            # For now, just pass the first sku for the downstream pipeline backward compatibility
            # The exact downstream handling of multiple SKUs will be done in G.1b.
            # But we don't short-circuit!
            extracted_sku = resolution["sku_ids"][0]


        # =====================================================================
        # STEP 2: HANDLE SUBSTITUTE INTENT
        # =====================================================================
        # Beginner Note: If the user asks for a "substitute" or "alternative"
        # for a drug, we route directly to the substitute finder instead of
        # the general RAG pipeline. This bypasses the LLM entirely and
        # returns real-time stock and pricing data from the database.

        if intents["substitute"] and extracted_sku is not None:
            logger.info(
                f"QuerySanitizer: Routing substitute intent for SKU "
                f"'{extracted_sku}' to substitute finder."
            )

            substitutes = find_clinical_substitutes(
                db, target_sku=extracted_sku, threshold=0.80
            )

            if substitutes:
                # Format the returned substitutes into a clean string
                lines = [f"Found alternatives for {extracted_sku}:"]
                for sub in substitutes:
                    lines.append(
                        f"Found alternative: {sub['sku_id']} - "
                        f"Stock: {sub['stock_qty']} - "
                        f"Price: ₹{sub['unit_price_inr']:.2f}"
                    )
                formatted_response = "\n".join(lines)
            else:
                formatted_response = (
                    f"No suitable clinical substitutes found for "
                    f"{extracted_sku} above 80% similarity threshold."
                )

            request_metrics["intent"] = bucket.value if hasattr(bucket, "value") else str(bucket)
            request_metrics["drug_resolved"] = True
            request_metrics["disambiguation_triggered"] = False
            request_metrics["path_taken"] = "substitute"
            return RAGQueryResponse(
                query=payload.query,
                answer=formatted_response,
                context_used=[],
                is_safe_to_dispense=True,
                system_lock_reason=None,
                citations=[],
            )

        # =====================================================================
        # STEP 3: ROUTE TO ADAPTIVE PIPELINE (WITH INTENTS FOR THE JUDGE)
        # =====================================================================
        # Pass the cleaned query and extracted SKU to the existing adaptive
        # router. If the SKU was already extracted by the sanitizer, the
        # router will skip its own SKU extraction and use ours.
        # If no SKU was found (extracted_sku is None), the router will
        # fall back to its own extraction logic or to Gemini.
        #
        # Phase 3 addition: We also pass the intents dict so the Rule Engine
        # (ClinicalSafetyJudge) can perform deterministic safety checks
        # BEFORE the LLM is called. The intents tell the Judge whether the
        # patient is pregnant, pediatric, or asking for a substitute.

        # Use the extracted SKU if found, otherwise fall back to the
        # frontend-provided SKU (payload.sku_id).
        final_sku = extracted_sku or payload.sku_id

        rag_data = await route_and_process_query(
            db=db,
            query=cleaned_query,
            sku_id=final_sku,
            intents=intents,
        )

        request_metrics["intent"] = bucket.value if hasattr(bucket, "value") else str(bucket)
        request_metrics["drug_resolved"] = True
        request_metrics["disambiguation_triggered"] = False
        request_metrics["path_taken"] = rag_data.get("path_taken")

        return RAGQueryResponse(
            query=payload.query,
            question_type=rag_data.get("question_type"),
            answer=rag_data["answer"],
            context_used=rag_data["context_used"],
            is_safe_to_dispense=rag_data.get("is_safe_to_dispense", True),
            system_lock_reason=rag_data.get("system_lock_reason"),
            citations=rag_data.get("citations", []),
        )
    except Exception:
        # we don't know the outcome, but log what we captured so far
        raise
    finally:
        latency_ms = round((time.monotonic() - start_time) * 1000, 2)
        request_metrics["latency_ms"] = latency_ms
        request_metrics["correlation_id"] = correlation_id
        logger.info(
            "request_completed",
            extra=request_metrics,
        )


# =========================================================================
# PHASE 9: CROSS-MODEL HYBRID ORCHESTRATOR (Substitute Finder)
# =========================================================================
# Beginner Note: This endpoint is designed for a specific real-world scenario:
# a pharmacist has scanned a medicine (e.g., "Pan 40") that is out of stock.
# The pharmacist needs to quickly find an alternative with:
#   1. A similar chemical composition (via AI vector similarity).
#   2. Physical stock available on the shelf (via inventory JOIN).
#   3. The lowest price (sorted cheapest first).
#
# The endpoint accepts a target SKU and a similarity threshold, then returns
# a list of substitutes ranked by price. If no substitutes meet the threshold,
# the pharmacist sees an empty list and can either ask the patient to wait
# for restocking or consult a senior pharmacist.

@router.post("/substitute", response_model=SubstituteResponseSchema)
async def find_substitute(
    payload: SubstituteRequestSchema,
    db: Session = Depends(get_database_session),
):
    """
    Find clinically similar substitutes for an out-of-stock medication.

    How it works (step-by-step for junior developers):
        1. We look up the AI embedding for the requested SKU in the
           clinical_knowledge_base table. This embedding is a 768-number
           vector that captures the medicine's chemical "fingerprint."
        2. We scan every OTHER medicine in the database, computing
           cosine similarity using pgvector's <=> operator.
        3. We only keep candidates whose similarity score is above the
           requested threshold (default 80% match).
        4. We join with medication_batches to filter out anything with
           zero stock and to compute the cheapest available price.
        5. Results are sorted by price ascending (cheapest first) so
           the pharmacist can offer the patient the most affordable option.

    Args:
        payload: The request body containing target_sku and optional threshold.

    Returns:
        A SubstituteResponseSchema with:
            - status: "success"
            - original_sku: The SKU the pharmacist asked about.
            - substitutes: A list of SubstituteItemSchema objects, empty
              if no suitable substitutes were found above the threshold.
    """
    substitutes = find_clinical_substitutes(
        db=db,
        target_sku=payload.target_sku,
        threshold=payload.threshold,
    )

    return SubstituteResponseSchema(
        status="success",
        original_sku=payload.target_sku,
        substitutes=[
            SubstituteItemSchema(**item)
            for item in substitutes
        ],
    )
