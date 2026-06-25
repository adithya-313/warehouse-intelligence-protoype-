from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.infrastructure.database import get_database_session
from app.api.dependencies import get_current_tenant
from app.domain.schemas import PatientCreate, TreatmentPlanCreate, TreatmentPlanResponse
from app.services.patient_service import register_patient, create_treatment_plan
from app.infrastructure.models import Patient

router = APIRouter()


@router.post("/register", status_code=status.HTTP_201_CREATED)
def api_register_patient(
    payload: PatientCreate,
    db: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant)
):
    """Registers a new patient. Strictly isolated by tenant auth header."""
    payload.tenant_id = tenant_id
    return register_patient(db, payload)


@router.post("/treatment-plan", response_model=TreatmentPlanResponse, status_code=status.HTTP_201_CREATED)
def api_create_treatment_plan(
    payload: TreatmentPlanCreate,
    db: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant)
):
    """Creates a treatment plan. Strictly isolated by tenant auth header."""
    payload.tenant_id = tenant_id

    patient = db.query(Patient).filter(
        Patient.patient_id == payload.patient_id,
        Patient.tenant_id == tenant_id
    ).first()

    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found or belongs to another pharmacy")

    return create_treatment_plan(db, payload)
