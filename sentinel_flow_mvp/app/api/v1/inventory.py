from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from app.infrastructure.database import get_database_session
from app.infrastructure.models import MedicationModel, MedicationBatchModel

router = APIRouter()

class InventorySearchResponse(BaseModel):
    batch_id: str
    sku_id: str
    name: str
    price: float
    available_quantity: int

@router.get("/search", response_model=List[InventorySearchResponse])
def search_inventory(
    q: str = Query(..., min_length=2),
    db: Session = Depends(get_database_session)
):
    """
    Search medication batches where the medication's sku_id matches the query.
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
