from typing import List
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.infrastructure.database import get_database_session
from app.infrastructure.models import PurchaseOrderModel, Tenant
from app.domain.schemas import PurchaseOrderBulkCreate
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

# Typeahead Catalog (mocked for MVP)
MOCK_CATALOG = [
    {"sku_id": "AMOX500", "name": "Amoxicillin 500mg"},
    {"sku_id": "PAN40", "name": "Pantoprazole 40mg"},
    {"sku_id": "PCM500", "name": "Paracetamol 500mg"},
    {"sku_id": "AZI500", "name": "Azithromycin 500mg"},
    {"sku_id": "LIP40", "name": "Lipitor 40mg"},
]


@router.get("/purchase-orders/catalog/search")
def search_catalog(q: str = ""):
    query = q.lower()
    return [
        item for item in MOCK_CATALOG
        if query in item["sku_id"].lower() or query in item["name"].lower()
    ]


@router.post("/purchase-orders")
def create_bulk_purchase_order(
    payload: PurchaseOrderBulkCreate,
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
        for item in payload.items:
            new_po = PurchaseOrderModel(
                po_id=po_id,
                tenant_id=tenant.tenant_id,
                supplier_id=payload.supplier_id,
                sku_id=item.sku_id.upper(),
                ordered_qty=item.ordered_qty,
                cost_price=item.cost_price,
                expected_mrp=item.expected_mrp,
                order_date=datetime.now(),
                expected_delivery_date=payload.expected_delivery_date,
                status="SUBMITTED",
            )
            db.add(new_po)

        db.commit()
        return {
            "po_id": po_id,
            "status": "SUBMITTED",
            "items_processed": len(payload.items),
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Bulk PO creation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail="Database transaction failed during Bulk PO creation.",
        )
