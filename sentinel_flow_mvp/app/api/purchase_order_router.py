import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.infrastructure.database import get_database_session
from app.infrastructure.models import PurchaseOrderModel, Tenant
from app.domain.schemas import PurchaseOrderCreate
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/purchase-orders")
def create_purchase_order(
    payload: PurchaseOrderCreate,
    db: Session = Depends(get_database_session)
):
    tenant = db.query(Tenant).first()
    if not tenant:
        raise HTTPException(status_code=500, detail="Tenant context missing")

    if payload.expected_delivery_date < datetime.now().date():
        raise HTTPException(
            status_code=400,
            detail="Expected delivery date cannot be in the past."
        )

    po_id = f"PO-{str(uuid.uuid4())[:8].upper()}"

    try:
        new_po = PurchaseOrderModel(
            po_id=po_id,
            tenant_id=tenant.tenant_id,
            supplier_id=payload.supplier_id,
            sku_id=payload.sku_id.upper(),
            ordered_qty=payload.ordered_qty,
            cost_price=payload.cost_price,
            expected_mrp=payload.expected_mrp,
            order_date=datetime.now(),
            expected_delivery_date=payload.expected_delivery_date,
            status="SUBMITTED",
        )
        db.add(new_po)
        db.commit()
        return {"po_id": po_id, "status": "SUBMITTED"}
    except Exception as e:
        db.rollback()
        logger.error(f"PO creation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail="Database transaction failed during PO creation.",
        )
