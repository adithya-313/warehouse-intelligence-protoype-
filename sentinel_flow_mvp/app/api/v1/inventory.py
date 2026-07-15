from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from app.infrastructure.database import get_database_session
from app.infrastructure.models import MedicationModel, MedicationBatchModel


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
    
    Beginner Note: Optimistic UI Model.
    The search is strictly read-only and fast. We no longer eagerly lock inventory
    in Redis during search. Concurrency is handled safely by the database during
    checkout (SELECT ... FOR UPDATE).
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

# [STORY: THE OPTIMISTIC INVENTORY PROJECTION]
# The frontend already knows how much stock is left from the search results.
# This endpoint strictly verifies the physical shelf count without using Redis locks.
# Concurrency is handled safely by the database during checkout (SELECT ... FOR UPDATE).

from sqlalchemy import func

@router.get("/projection/{sku_id}")
async def get_real_time_stock_projection(sku_id: str, db: Session = Depends(get_database_session)):
    """
    Returns the physical available stock from the database to trigger critical alerts.
    """
    logger.info(f"Verifying physical stock for critical alert check: {sku_id}")
    
    # Scene 1: Look at the physical shelves (PostgreSQL)
    db_stock = db.query(MedicationBatchModel)\
                 .filter(MedicationBatchModel.sku_id == sku_id)\
                 .with_entities(func.sum(MedicationBatchModel.available_quantity))\
                 .scalar() or 0
    
    return {
        "sku_id": sku_id,
        "true_available_stock": int(db_stock)
    }
