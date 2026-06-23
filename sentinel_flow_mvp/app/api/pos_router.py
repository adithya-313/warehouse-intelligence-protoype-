from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from app.domain.schemas import MedicationSoldEvent
from app.services.kafka_producer import publish_medication_sold
from app.infrastructure.db.database import get_database_session
from app.services.fefo_engine import get_optimal_fefo_batch
from app.services.recommendation_engine import get_clinical_cross_sells, get_high_margin_generics
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/sell", status_code=202)
async def record_medication_sale(event: MedicationSoldEvent):
    """
    High-throughput endpoint for Point-of-Sale systems.
    Instantly accepts the transaction and publishes it to the Kafka event mesh.
    """
    try:
        # Publish to Kafka/Redpanda
        await publish_medication_sold(event)
        
        # Return 202 Accepted instantly. The actual DB update happens asynchronously.
        return {"status": "accepted", "message": "Transaction published to event mesh"}
    except Exception as e:
        logger.error(f"Failed to publish POS event: {e}")
        raise HTTPException(status_code=500, detail="Event mesh unavailable")

@router.get("/fefo-routing/{sku_id}")
async def get_fefo_routing(
    sku_id: str, 
    qty: int = 1, 
    db: Session = Depends(get_database_session)
):
    """
    Overrides standard FIFO. Analyzes the batch matrix and instructs the clerk 
    exactly which physical box to pull from the shelf to minimize expiry waste.
    """
    routing_info = get_optimal_fefo_batch(db, sku_id, qty)
    
    if not routing_info:
        raise HTTPException(
            status_code=404, 
            detail="No unexpired stock available for this medication."
        )
        
    return {
        "status": "success",
        "routing": routing_info
    }

@router.get("/recommendations/{sku_id}")
async def get_smart_recommendations(
    sku_id: str, 
    db: Session = Depends(get_database_session)
):
    """
    Surfaces clinical cross-sells (via Graph Engine) and high-margin generic 
    alternatives (via API matching) to maximize pharmacy profit at checkout.
    """
    cross_sells = get_clinical_cross_sells(sku_id)
    generics = get_high_margin_generics(db, sku_id)
    
    return {
        "status": "success",
        "scanned_sku": sku_id,
        "cross_sells": cross_sells,
        "generic_alternatives": generics
    }
