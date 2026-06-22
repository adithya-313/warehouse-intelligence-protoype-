from fastapi import APIRouter, HTTPException
from app.domain.schemas import MedicationSoldEvent
from app.services.kafka_producer import publish_medication_sold
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
