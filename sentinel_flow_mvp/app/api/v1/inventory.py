from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from app.infrastructure.database import get_database_session
from app.infrastructure.models import MedicationModel, MedicationBatchModel

# Import the Redis inventory lock so that when a pharmacist selects a batch
# via search, we reserve it for 60 seconds (preventing double-sales).
from app.core.redis_client import try_acquire_inventory_lock

import logging

logger = logging.getLogger(__name__)

router = APIRouter()

class InventorySearchResponse(BaseModel):
    batch_id: str
    sku_id: str
    name: str
    price: float
    available_quantity: int

@router.get("/search", response_model=List[InventorySearchResponse])
async def search_inventory(
    q: str = Query(..., min_length=2),
    db: Session = Depends(get_database_session)
):
    """
    Search medication batches where the medication's sku_id matches the query.

    FEFO SAGA LOCK:
    Each batch returned in search results gets a temporary 60-second lock in Redis.
    This reserves the batch so that when the pharmacist proceeds to checkout,
    the batch hasn't been sold to someone else in the meantime.

    Beginner Note: Think of this as putting a "Reserved" sticky note on the
    physical box when the pharmacist scans the barcode. The sticky note expires
    in 60 seconds — enough time to complete the sale.
    """
    results = (
        db.query(
            MedicationBatchModel.batch_id,
            MedicationBatchModel.sku_id,
            MedicationBatchModel.max_retail_price,
            MedicationBatchModel.available_quantity
        )
        .join(MedicationModel, MedicationBatchModel.sku_id == MedicationModel.sku_id)
        .filter(MedicationModel.sku_id.ilike(f"%{q}%"))
        .limit(10)
        .all()
    )
    
    # Create a Redis lock for each batch in the search results
    # so that checkout can verify the batch is still available.
    for row in results:
        lock_acquired: bool = await try_acquire_inventory_lock(
            batch_id=row.batch_id,
            quantity=row.available_quantity,
            ttl_seconds=60,
        )
        if lock_acquired:
            logger.debug(f"FEFO lock acquired for batch={row.batch_id} during search")
    
    return [
        InventorySearchResponse(
            batch_id=row.batch_id,
            sku_id=row.sku_id,
            name=row.sku_id,  # Map sku_id to name
            price=float(row.max_retail_price),
            available_quantity=row.available_quantity
        )
        for row in results
    ]
