from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.infrastructure.database import get_database_session
from app.services.supplier_scorecard_service import generate_financial_scorecard
from app.domain.schemas import DistributorScorecardResponse
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/{supplier_id}/scorecard", response_model=DistributorScorecardResponse)
async def get_supplier_scorecard(
    supplier_id: str, 
    db: Session = Depends(get_database_session)
):
    """
    Generates a real-time financial scorecard for a specific distributor.
    Calculates exact Rupee losses due to delivery shortfalls to aid in vendor negotiation.
    """
    scorecard = generate_financial_scorecard(db, supplier_id)
    
    if not scorecard:
        raise HTTPException(
            status_code=404, 
            detail="No historical order data found for this supplier."
        )
        
    return scorecard
