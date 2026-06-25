import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.infrastructure.models import Patient, TreatmentPlan
from app.domain.schemas import PatientCreate, TreatmentPlanCreate


def register_patient(db: Session, payload: PatientCreate) -> Patient:
    """Idempotent patient registration."""
    existing = db.query(Patient).filter(Patient.phone_number == payload.phone_number).first()
    if existing:
        return existing

    new_patient = Patient(**payload.model_dump())
    db.add(new_patient)
    db.commit()
    db.refresh(new_patient)
    return new_patient


def create_treatment_plan(db: Session, payload: TreatmentPlanCreate) -> TreatmentPlan:
    """Calculates the exact depletion horizon and creates the ledger entry."""

    days_until_empty = payload.total_quantity_dispensed / payload.daily_dosage

    start_dt = datetime.now(timezone.utc)
    depletion_dt = start_dt + timedelta(days=days_until_empty)

    plan = TreatmentPlan(
        plan_id=f"PLAN-{uuid.uuid4().hex[:8].upper()}",
        patient_id=payload.patient_id,
        sku_id=payload.sku_id,
        daily_dosage=payload.daily_dosage,
        total_quantity_dispensed=payload.total_quantity_dispensed,
        start_date=start_dt,
        projected_depletion_date=depletion_dt,
        is_active=True
    )

    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan
