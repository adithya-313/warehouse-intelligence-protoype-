import logging
from celery import shared_task
from sentence_transformers import SentenceTransformer
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import ClinicalKnowledgeBase

logger = logging.getLogger(__name__)

# GLOBAL CACHE: We load the model once per worker process to save RAM and CPU time.
EMBEDDING_MODEL = None

def get_embedding_model():
    """Singleton pattern to load the PubMedBERT model."""
    global EMBEDDING_MODEL
    if EMBEDDING_MODEL is None:
        logger.info("Loading PubMedBERT model into memory. This may take a moment...")
        # We enforce CPU execution to ensure stability across all environments.
        EMBEDDING_MODEL = SentenceTransformer("NeuML/pubmedbert-base-embeddings", device="cpu")
    return EMBEDDING_MODEL

@shared_task(bind=True, max_retries=3, queue='embeddings')
def generate_and_store_embedding(self, sku_id: str, content: str, metadata: dict = None):
    """
    Background task to convert clinical text into a 768-dimensional vector.
    """
    if metadata is None:
        metadata = {}

    try:
        model = get_embedding_model()
        
        # 1. Generate the 768-dimensional vector
        # .encode() returns a numpy array. We convert it to a standard Python list for pgvector.
        vector = model.encode(content).tolist()
        
        # 2. Database Transaction
        db = SessionLocal()
        try:
            # Idempotency Check: Prevent duplicate knowledge entries
            existing = db.query(ClinicalKnowledgeBase).filter(
                ClinicalKnowledgeBase.sku_id == sku_id,
                ClinicalKnowledgeBase.content == content
            ).first()
            
            if existing:
                logger.info(f"Knowledge already exists for SKU {sku_id}. Skipping duplicate.")
                return {"status": "skipped", "sku_id": sku_id}

            # 3. Save to Database
            new_record = ClinicalKnowledgeBase(
                sku_id=sku_id,
                content=content,
                embedding=vector,
                metadata_payload=metadata
            )
            db.add(new_record)
            db.commit()
            
            logger.info(f"Successfully stored 768-dim embedding for SKU {sku_id}.")
            return {"status": "success", "sku_id": sku_id}
            
        except Exception as db_err:
            db.rollback()
            raise db_err
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Embedding generation failed: {str(e)}")
        # Resilience: Retry with exponential backoff (2s, 4s, 8s...)
        raise self.retry(exc=e, countdown=2 ** self.request.retries)
