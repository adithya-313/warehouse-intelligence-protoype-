from datetime import date
from sqlalchemy.orm import Session
from app.infrastructure.models import MedicationBatchModel
import logging

logger = logging.getLogger(__name__)

def get_optimal_fefo_batch(db: Session, sku_id: str, required_qty: int = 1):
    """
    Finds the oldest unexpired batch for a given medication.
    
    Beginner Note: FEFO stands for First-Expire-First-Out. We sort by expiry_date
    so the pharmacy sells the medicine that expires soonest, preventing waste.
    """
    today = date.today()
    
    # Query the database for batches of this SKU that:
    # 1. Are not expired (expiry_date >= today)
    # 2. Have stock available (available_quantity > 0)
    # Then sort them by expiry_date ascending (oldest first)
    optimal_batch = db.query(MedicationBatchModel).filter(
        MedicationBatchModel.sku_id == sku_id,
        MedicationBatchModel.expiry_date >= today,
        MedicationBatchModel.available_quantity > 0
    ).order_by(MedicationBatchModel.expiry_date.asc()).first()
    
    if not optimal_batch:
        logger.warning(f"No unexpired stock found for SKU: {sku_id}")
        return None
        
    # Return a clear instruction payload for the frontend UI
    return {
        "batch_id": optimal_batch.batch_id,
        "expiry_date": optimal_batch.expiry_date,
        "available_quantity": optimal_batch.available_quantity,
        "shelf_location": optimal_batch.shelf_location,
        # We also hand back the price here now, since Phase 3's clinical
        # narration needs it — every other caller just ignores this new key,
        # so nothing existing breaks.
        "max_retail_price": optimal_batch.max_retail_price,
        "instruction": f"Pull from {optimal_batch.shelf_location}. Batch {optimal_batch.batch_id} expires on {optimal_batch.expiry_date}."
    }
