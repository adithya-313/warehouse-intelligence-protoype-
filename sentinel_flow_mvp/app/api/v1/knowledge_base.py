from fastapi import APIRouter, status
from app.domain.schemas import KnowledgeIngestionRequest, KnowledgeIngestionResponse
from app.workers.embedding_tasks import generate_and_store_embedding

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
