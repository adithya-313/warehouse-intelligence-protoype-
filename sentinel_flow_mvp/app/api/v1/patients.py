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


@router.get("/active-treatment-count")
def get_active_treatment_count(
    db: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant)
):
    """Returns the total number of active treatment plans."""
    from app.infrastructure.models import TreatmentPlan
    
    # First, we connect to the database to find all active treatment plans for this tenant.
    # We count how many rows match the is_active flag.
    total_active_patients_count = db.query(TreatmentPlan).filter(
        TreatmentPlan.tenant_id == tenant_id,
        TreatmentPlan.is_active == True
    ).count()
    
    return {"count": total_active_patients_count}


@router.get("/upcoming-refills")
def get_upcoming_refills(
    db: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant)
):
    """Finds patients whose medications will deplete within the next 7 days."""
    from app.infrastructure.models import TreatmentPlan
    from datetime import datetime, timedelta, timezone
    
    # We need to know what today's date is to compare against the depletion date.
    current_time = datetime.now(timezone.utc)
    future_time_threshold = current_time + timedelta(days=7)
    
    # We query the TreatmentPlan table to find plans that are active
    # and will run out of medication between now and the threshold date.
    upcoming_refills_query = db.query(TreatmentPlan).filter(
        TreatmentPlan.tenant_id == tenant_id,
        TreatmentPlan.is_active == True,
        TreatmentPlan.projected_depletion_date >= current_time,
        TreatmentPlan.projected_depletion_date <= future_time_threshold
    ).all()
    
    # We create a list to hold the formatted refill objects for the frontend.
    formatted_refills_list = []
    
    # We loop over every treatment plan found in the query to format the response.
    for plan in upcoming_refills_query:
        # We need the patient's name and phone number for the refill alert.
        # We find the patient linked to this plan.
        linked_patient = db.query(Patient).filter(
            Patient.patient_id == plan.patient_id,
            Patient.tenant_id == tenant_id
        ).first()
        
        if linked_patient:
            formatted_refills_list.append({
                "patient_name": linked_patient.name,
                "phone": linked_patient.phone_number,
                "medication": plan.sku_id,
                "depletion_date": plan.projected_depletion_date
            })
            
    return formatted_refills_list


@router.get("/disease-stats")
def get_disease_statistics(
    db: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant)
):
    """Calculates the distribution of chronic diseases among the patient population."""
    # We query all patients belonging to the current pharmacy tenant.
    all_tenant_patients = db.query(Patient).filter(
        Patient.tenant_id == tenant_id
    ).all()
    
    # We create a dictionary to keep a tally of each disease we encounter.
    disease_frequency_map = {}
    
    # We loop through every single patient in our list.
    for patient in all_tenant_patients:
        # Some patients might not have any chronic diseases, so we skip if it's empty.
        if patient.chronic_diseases:
            # We loop through each disease tag the patient has.
            for disease_tag in patient.chronic_diseases:
                # If we've seen this disease before, we increment the tally by 1.
                if disease_tag in disease_frequency_map:
                    disease_frequency_map[disease_tag] = disease_frequency_map[disease_tag] + 1
                # If this is a new disease, we add it to the tally and start it at 1.
                else:
                    disease_frequency_map[disease_tag] = 1
                    
    # We return the final tallied map to the frontend.
    # We format it as a list of objects so the charting library can easily read it.
    formatted_disease_stats_list = []
    for disease_name, disease_count in disease_frequency_map.items():
        formatted_disease_stats_list.append({
            "name": disease_name,
            "value": disease_count
        })
        
    return formatted_disease_stats_list
