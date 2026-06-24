import logging
from sqlalchemy.orm import Session
from app.infrastructure.models import ClinicalKnowledgeBase
from app.workers.embedding_tasks import get_embedding_model

logger = logging.getLogger(__name__)

# CLINICAL SAFETY CONSTRAINT: 
# If the AI match is less than 85% similar, we reject it to prevent hallucinations.
MINIMUM_CONFIDENCE_THRESHOLD = 0.85

def execute_clinical_search(db: Session, query: str, sku_id: str = None, top_k: int = 3) -> dict:
    """
    Executes a vector similarity search against the clinical knowledge base.
    """
    # 1. Convert the user's text query into a 768-dimensional vector using PubMedBERT
    model = get_embedding_model()
    query_vector = model.encode(query).tolist()

    # 2. Build the database query using pgvector's cosine distance operator (<=>)
    # Note: Cosine distance is (1 - Cosine Similarity). 
    # So a distance of 0.1 means a similarity of 0.90 (90%).
    base_query = db.query(
        ClinicalKnowledgeBase,
        ClinicalKnowledgeBase.embedding.cosine_distance(query_vector).label("distance")
    )

    # 3. Apply optional SKU filter
    if sku_id:
        base_query = base_query.filter(ClinicalKnowledgeBase.sku_id == sku_id)

    # 4. Execute search, order by closest distance (highest similarity)
    raw_results = base_query.order_by("distance").limit(top_k).all()

    formatted_results = []
    safety_warning = None

    # 5. Process results and enforce the Safety Circuit Breaker
    for record, distance in raw_results:
        # Convert distance back to a standard percentage (0.0 to 1.0)
        similarity_score = 1.0 - distance
        
        if similarity_score >= MINIMUM_CONFIDENCE_THRESHOLD:
            formatted_results.append({
                "sku_id": record.sku_id,
                "content": record.content,
                "confidence_score": round(similarity_score, 4),
                "metadata_payload": record.metadata_payload
            })
        else:
            logger.warning(f"Search result rejected. Confidence {similarity_score} is below threshold.")

    # 6. Graceful Degradation: If no results passed the safety check
    if not formatted_results:
        safety_warning = "CLINICAL SAFETY BREAKER: No high-confidence matches found. Please consult a Senior Pharmacist or official CDSCO guidelines."

    return {
        "results": formatted_results,
        "safety_warning": safety_warning
    }
