import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.infrastructure.database import get_database_session
from app.infrastructure.models import SupplierModel
from app.services.supplier_scorecard_service import generate_financial_scorecard
from app.domain.schemas import DistributorScorecardResponse, SupplierCreateRequest
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


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
