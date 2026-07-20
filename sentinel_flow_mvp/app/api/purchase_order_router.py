from typing import List
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.infrastructure.database import get_database_session
from app.infrastructure.models import MedicationModel, PurchaseOrderModel, Tenant
from app.domain.schemas import PurchaseOrderBulkCreate, PurchaseOrderReceiveBulk
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/purchase-orders")
def list_purchase_orders(db: Session = Depends(get_database_session)):
    pos = db.query(PurchaseOrderModel).order_by(
        PurchaseOrderModel.order_date.desc()
    ).all()

    ledger = {}
    for po in pos:
        if po.po_id not in ledger:
            ledger[po.po_id] = {
                "po_id": po.po_id,
                "supplier_id": po.supplier_id,
                "order_date": po.order_date.isoformat() if po.order_date else None,
                "expected_delivery_date": po.expected_delivery_date.isoformat() if po.expected_delivery_date else None,
                "status": po.status,
                "item_count": 0,
                "total_value_rupees": 0.0,
            }
        ledger[po.po_id]["item_count"] += 1
        ledger[po.po_id]["total_value_rupees"] += float(po.ordered_qty * po.cost_price)

    return list(ledger.values())

@router.get("/purchase-orders/catalog/search")
def search_catalog(q: str = "", db: Session = Depends(get_database_session)):
    query = q.lower()
    results = db.query(MedicationModel).filter(
        MedicationModel.sku_id.ilike(f"%{query}%")
    ).all()
    return [
        {"sku_id": row.sku_id, "name": row.sku_id}
        for row in results
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
    except IntegrityError as e:
        db.rollback()
        logger.error(f"Bulk PO integrity error: {e}")
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate or conflicting item in purchase order. Verify the SKU list has no duplicates. Error: {e}",
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Bulk PO creation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail="Database transaction failed during Bulk PO creation.",
        )


@router.post("/purchase-orders/receive")
def receive_bulk_purchase_order(
    payload: PurchaseOrderReceiveBulk,
    db: Session = Depends(get_database_session)
):
    po_items = db.query(PurchaseOrderModel).filter(
        PurchaseOrderModel.po_id == payload.po_id,
        PurchaseOrderModel.status == "SUBMITTED"
    ).all()

    if not po_items:
        raise HTTPException(
            status_code=404,
            detail="Active Purchase Order not found or already fulfilled."
        )

    delivery_map = {item.sku_id.upper(): item.delivered_qty for item in payload.items}

    try:
        for po in po_items:
            delivered = delivery_map.get(po.sku_id, 0)
            po.actual_delivery_date = payload.actual_delivery_date
            po.delivered_qty = delivered
            po.status = "FULFILLED"

        db.commit()
        return {
            "po_id": payload.po_id,
            "status": "FULFILLED",
            "lines_processed": len(po_items),
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Database transaction failed during Intake.",
        )
