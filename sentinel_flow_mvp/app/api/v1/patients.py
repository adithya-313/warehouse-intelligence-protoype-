from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.infrastructure.database import get_database_session
from app.domain.schemas import PatientCreate, TreatmentPlanCreate, TreatmentPlanResponse
from app.services.patient_service import register_patient, create_treatment_plan

router = APIRouter()


@router.post("/register", status_code=status.HTTP_201_CREATED)
def api_register_patient(payload: PatientCreate, db: Session = Depends(get_database_session)):
    """Registers a new patient for chronic care tracking."""
    return register_patient(db, payload)


@router.post("/treatment-plan", response_model=TreatmentPlanResponse, status_code=status.HTTP_201_CREATED)
def api_create_treatment_plan(payload: TreatmentPlanCreate, db: Session = Depends(get_database_session)):
    """Creates a treatment plan and calculates the depletion horizon."""
    from app.infrastructure.models import Patient
    if not db.query(Patient).filter(Patient.patient_id == payload.patient_id).first():
        raise HTTPException(status_code=404, detail="Patient not found")

    return create_treatment_plan(db, payload)
