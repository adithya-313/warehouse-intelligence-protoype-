from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from app.infrastructure.database import get_database_session
from app.infrastructure.models import MedicationModel, MedicationBatchModel

# Import the Redis inventory lock so that when a pharmacist selects a batch
# via search, we reserve it for 60 seconds (preventing double-sales).
from app.core.redis_client import try_acquire_inventory_lock
from app.api.dependencies import get_current_tenant

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
    db: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant)
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
        .filter(MedicationBatchModel.tenant_id == tenant_id)
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

# [STORY: THE REAL-TIME INVENTORY PROJECTION]
# Chapter 1: The Illusion of Stock
# In a busy pharmacy, what is on the shelf (Database) isn't always what is available to sell.
# If another pharmacist has an item in their checkout cart, that item is "locked" in Redis.
# To show the TRUE available stock, we must calculate: Database Quantity - Redis Locked Quantity.

from sqlalchemy import func
from app.core.redis_client import get_active_lock_count_for_sku

@router.get("/projection/{sku_id}")
async def get_real_time_stock_projection(sku_id: str, db: Session = Depends(get_database_session)):
    """
    Returns the true available stock by combining Database records and Redis locks.
    """
    logger.info(f"Checking stock projection for SKU: {sku_id}")
    
    # Scene 1: Look at the physical shelves (PostgreSQL)
    # We sum up all the available quantity across all non-expired batches for this SKU.
    db_stock = db.query(MedicationBatchModel)\
                 .filter(MedicationBatchModel.sku_id == sku_id)\
                 .with_entities(func.sum(MedicationBatchModel.available_quantity))\
                 .scalar() or 0
                 
    # Scene 2: Check the active shopping carts (Redis)
    # How many of these items are currently locked in other transactions?
    locked_stock = await get_active_lock_count_for_sku(sku_id)
    
    # Scene 3: The Truth
    # The actual stock we can safely show to the user.
    true_available_stock = db_stock - locked_stock
    
    # We return a psychological health indicator along with the data.
    health_status = "CRITICAL" if true_available_stock <= 5 else "HEALTHY"
    
    return {
        "sku_id": sku_id,
        "database_stock": int(db_stock),
        "locked_in_carts": locked_stock,
        "true_available_stock": int(true_available_stock),
        "health_status": health_status
    }
