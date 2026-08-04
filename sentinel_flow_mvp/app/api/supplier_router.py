import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.infrastructure.database import get_database_session
from app.infrastructure.models import SupplierModel, PurchaseOrderModel
from app.api.deps import get_current_tenant
from app.services.supplier_scorecard_service import generate_financial_scorecard
from app.domain.schemas import DistributorScorecardResponse, SupplierCreateRequest, SupplierListResponse
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

from pydantic import BaseModel
from datetime import date
from typing import List, Optional

class SupplierOrderLineItem(BaseModel):
    po_id: str
    sku_id: str
    order_date: date
    expected_delivery_date: date
    actual_delivery_date: Optional[date] = None
    status: str
    ordered_qty: int
    delivered_qty: int
    cost_price: float
    expected_mrp: float

    class Config:
        orm_mode = True
        from_attributes = True

@router.get("/{supplier_id}/orders", response_model=List[SupplierOrderLineItem])
def list_supplier_orders(
    supplier_id: str,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_database_session)
):
    """Returns all PO line items for a specific supplier, scoped to the tenant."""
    orders = db.query(PurchaseOrderModel).filter(
        PurchaseOrderModel.supplier_id == supplier_id,
        PurchaseOrderModel.tenant_id == tenant_id
    ).order_by(desc(PurchaseOrderModel.order_date)).all()
    
    return orders

@router.get("/{supplier_id}/scorecard", response_model=DistributorScorecardResponse)
async def get_supplier_scorecard(
    supplier_id: str,
    db: Session = Depends(get_database_session)
):
    """Generates a real-time financial scorecard for a specific distributor."""
    supplier = db.query(SupplierModel).filter(
        SupplierModel.supplier_id == supplier_id
    ).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found.")
    return generate_financial_scorecard(db, supplier_id)


@router.get("", response_model=SupplierListResponse)
def list_suppliers(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_database_session)
):
    """
    Fetches a paginated list of all onboarded vendors from the database.
    This replaces the hardcoded mock array on the frontend Vendor Intelligence page.
    """
    # 1. Validate the pagination parameters to prevent abuse or database strain.
    if limit <= 0 or limit > 200:
        raise HTTPException(
            status_code=400, 
            detail="Limit must be between 1 and 200."
        )
    if offset < 0:
        raise HTTPException(
            status_code=400, 
            detail="Offset cannot be negative."
        )
        
    logger.info(f"Fetching supplier list (limit={limit}, offset={offset})")

    try:
        # 2. Query the total count of suppliers (for frontend pagination UI).
        total_suppliers = db.query(SupplierModel).count()
        
        # 3. Fetch the specific page of suppliers from the database.
        suppliers = db.query(SupplierModel).offset(offset).limit(limit).all()
        
        # 4. Transform the database models into the shape expected by the frontend.
        items = []
        for supplier in suppliers:
            # Safely extract the vendor name from the JSONB metadata payload.
            meta = supplier.industry_specific_metadata or {}
            vendor_name = meta.get("name", "Unknown Vendor")
            
            items.append({
                "supplier_id": supplier.supplier_id,
                "name": vendor_name,
                "industry_vertical": supplier.industry_vertical,
            })
            
        logger.info(f"Successfully fetched {len(items)} suppliers.")
        
        # 5. Return the structured paginated response.
        return SupplierListResponse(
            items=items,
            total=total_suppliers,
            limit=limit,
            offset=offset
        )
        
    except Exception as e:
        logger.error(f"Failed to fetch suppliers from database: {e}")
        raise HTTPException(
            status_code=500,
            detail="An internal database error occurred while fetching suppliers."
        )

@router.post("", response_model=DistributorScorecardResponse)
def onboard_supplier(
    payload: SupplierCreateRequest,
    db: Session = Depends(get_database_session)
):
    """Onboards a new vendor and returns a baseline scorecard."""
    new_id = f"SUPP-{str(uuid.uuid4())[:8].upper()}"

    meta = {"name": payload.name, "contact": payload.contact_email}

    try:
        new_supplier = SupplierModel(
            supplier_id=new_id,
            system_origin="USER_PORTAL",
            industry_vertical=payload.industry_vertical,
            industry_specific_metadata=meta,
        )
        db.add(new_supplier)
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to onboard supplier: {e}")
        raise HTTPException(
            status_code=500,
            detail="Database transaction failed during vendor onboarding.",
        )

    return DistributorScorecardResponse(
        supplier_id=new_id,
        name=payload.name,
        financial_loss_rupees=0.0,
        delivery_success_rate=100,
        trust_score=100,
        risk_level="TRUSTED",
        recent_failures=0,
    )
