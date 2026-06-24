from fastapi import APIRouter, status, Depends
from sqlalchemy.orm import Session
from app.infrastructure.database import get_database_session
from app.domain.schemas import KnowledgeIngestionRequest, KnowledgeIngestionResponse, SemanticSearchRequest, SemanticSearchResponse
from app.workers.embedding_tasks import generate_and_store_embedding
from app.services.semantic_search import execute_clinical_search

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
