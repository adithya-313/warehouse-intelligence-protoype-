from fastapi import APIRouter, status, Depends
from sqlalchemy.orm import Session
from app.infrastructure.database import get_database_session
from app.domain.schemas import KnowledgeIngestionRequest, KnowledgeIngestionResponse, SemanticSearchRequest, SemanticSearchResponse, RAGQueryRequest, RAGQueryResponse, SubstituteRequestSchema, SubstituteResponseSchema, SubstituteItemSchema
from app.workers.embedding_tasks import generate_and_store_embedding
from app.services.semantic_search import execute_clinical_search, find_clinical_substitutes
from app.services.rag_pipeline import route_and_process_query
import re

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
      - Clinical/subjective queries → answered via Gemini RAG with clinical context.
    """
    query_lower = payload.query.lower()
    if "substitute" in query_lower or "alternative" in query_lower:
        # ---------------------------------------------------------------------
        # STORY COMMENT:
        # We intercept queries asking for a "substitute" or "alternative".
        # We use a regex (re.search) to find a SKU code (e.g., AMOXI-500 or PAN-40).
        # The regex r"([a-zA-Z]+-\d+)" looks for letters, a hyphen, and numbers.
        # This allows us to bridge the chat UI directly to the vector database,
        # bypassing the expensive LLM entirely and returning real-time relation data.
        # ---------------------------------------------------------------------
        sku_match = re.search(r"([A-Z]+-\d+)", payload.query, re.IGNORECASE)
        if sku_match:
            sku = sku_match.group(1).upper()
            substitutes = find_clinical_substitutes(db, target_sku=sku, threshold=0.80)
            
            if substitutes:
                # Format the returned substitutes into a clean string
                lines = [f"Found alternatives for {sku}:"]
                for sub in substitutes:
                    lines.append(f"Found alternative: {sub['sku_id']} - Stock: {sub['stock_qty']} - Price: ₹{sub['unit_price_inr']:.2f}")
                formatted_response = "\n".join(lines)
            else:
                formatted_response = f"No suitable clinical substitutes found for {sku} above 80% similarity threshold."
                
            return RAGQueryResponse(
                query=payload.query,
                answer=formatted_response,
                context_used=[]
            )

    rag_data = route_and_process_query(
        db=db,
        query=payload.query,
        sku_id=payload.sku_id
    )

    return RAGQueryResponse(
        query=payload.query,
        answer=rag_data["answer"],
        context_used=rag_data["context_used"]
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
