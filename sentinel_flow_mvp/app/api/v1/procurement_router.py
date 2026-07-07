import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.infrastructure.database import get_database_session
from app.infrastructure.models import (
    PurchaseOrderModel, SupplierModel, ExogenousCovariateModel, MedicationModel
)
from app.api.dependencies import get_current_tenant

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/procurement", tags=["Procurement"])

# --- SCHEMAS ---
class DiseaseWaveAlert(BaseModel):
    sku_id: str
    sku_name: str
    probability_score: float
    expected_volume: int
    recommended_supplier_id: str
    warning_message: str

class AutoPORequest(BaseModel):
    sku_id: str
    supplier_id: str
    quantity: int

class AutoPOResponse(BaseModel):
    po_id: int
    status: str
    message: str

# --- ENDPOINTS ---
@router.get("/disease-wave-alerts", response_model=list[DiseaseWaveAlert])
def get_disease_wave_alerts(
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_database_session)
):
    """
    Detects incoming disease waves based on exogenous covariates (weather/trends)
    and recommends preemptive stock procurement.
    """
    # 1. Fetch latest covariates to simulate Chronos-2 wave detection
    latest_covariate = db.query(ExogenousCovariateModel).order_by(
        desc(ExogenousCovariateModel.timestamp)
    ).first()

    alerts = []
    # Heuristic: If search trends for fever are high, flag Paracetamol
    if latest_covariate and (latest_covariate.trend_score or 0) > 70.0:
        # Find a relevant SKU (fallback to first available if specific one missing)
        med = db.query(MedicationModel).filter(MedicationModel.sku_id.ilike("%para%")).first()
        if not med:
            med = db.query(MedicationModel).first()
            
        if med:
            # 2. Find the highest-performing supplier (most completed POs)
            best_supplier = db.query(
                PurchaseOrderModel.supplier_id,
                func.count(PurchaseOrderModel.po_id).label('completed_count')
            ).filter(
                PurchaseOrderModel.status == 'COMPLETED'
            ).group_by(PurchaseOrderModel.supplier_id).order_by(
                desc('completed_count')
            ).first()

            # Fallback to any supplier if no history exists
            supplier_id = best_supplier.supplier_id if best_supplier else "SUPP-001"

            alerts.append(DiseaseWaveAlert(
                sku_id=med.sku_id,
                sku_name=med.sku_id,
                probability_score=0.89,
                expected_volume=500,
                recommended_supplier_id=supplier_id,
                warning_message=f"High localized search trends detected for viral fever. Preemptive stock recommended."
            ))
    
    return alerts

@router.post("/auto-po", response_model=AutoPOResponse)
def create_auto_purchase_order(
    request: AutoPORequest,
    tenant_id: str = Depends(get_current_tenant),
    db: Session = Depends(get_database_session)
):
    """
    Creates a 1-click Purchase Order. 
    Idempotent: Prevents duplicate pending orders for the same SKU.
    """
    # 1. Idempotency Check: Does a PENDING order already exist for this SKU?
    existing_po = db.query(PurchaseOrderModel).filter(
        PurchaseOrderModel.sku_id == request.sku_id,
        PurchaseOrderModel.status == 'PENDING'
    ).first()

    if existing_po:
        logger.info(f"Idempotency triggered: PO already exists for SKU {request.sku_id}")
        return AutoPOResponse(
            po_id=existing_po.po_id, 
            status=existing_po.status, 
            message="Existing pending order found. No new order created."
        )

    # 2. Create new PO
    import uuid
    new_po = PurchaseOrderModel(
        po_id=str(uuid.uuid4()), # Need a string PO id
        supplier_id=request.supplier_id,
        sku_id=request.sku_id,
        ordered_qty=request.quantity,
        cost_price=10.0, # Mock price for MVP
        expected_mrp=15.0,
        order_date=datetime.now(timezone.utc),
        expected_delivery_date=datetime.now(timezone.utc) + timedelta(days=2),
        status='PENDING'
    )
    
    db.add(new_po)
    db.commit()
    db.refresh(new_po)
    
    logger.info(f"Successfully created preemptive PO {new_po.po_id} for SKU {request.sku_id}")
    return AutoPOResponse(
        po_id=hash(new_po.po_id) % 100000, # Mock a number or update AutoPOResponse to str
        status=new_po.status, 
        message="Purchase order successfully routed to highest-performing distributor."
    )
