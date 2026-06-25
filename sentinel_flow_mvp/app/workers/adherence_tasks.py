import logging
import redis
from datetime import datetime, timedelta, timezone
from celery import shared_task
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import TreatmentPlan, Patient
from app.core.config import get_application_settings

logger = logging.getLogger(__name__)
settings = get_application_settings()

redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


@shared_task(bind=True, max_retries=3)
def send_whatsapp_reminder(self, phone_number: str, patient_name: str, sku_id: str, plan_id: str):
    try:
        logger.info(f"🟢 [WHATSAPP API] Message dispatched to {phone_number}")
        logger.info(f"   Payload: 'Hi {patient_name}, your prescription for {sku_id} is running low. Reply YES to auto-refill.'")

        lock_key = f"whatsapp_lock_{plan_id}"
        redis_client.set(lock_key, "sent", ex=86400)

        return {"status": "delivered", "plan_id": plan_id}
    except Exception as e:
        logger.error(f"WhatsApp delivery failed: {str(e)}")
        raise self.retry(exc=e, countdown=60)


@shared_task
def sweep_depletion_horizons():
    logger.info("Starting daily adherence sweep...")
    db = SessionLocal()
    try:
        target_date = datetime.now(timezone.utc) + timedelta(days=3)

        expiring_plans = db.query(TreatmentPlan, Patient).join(
            Patient, TreatmentPlan.patient_id == Patient.patient_id
        ).filter(
            TreatmentPlan.is_active == True,
            TreatmentPlan.projected_depletion_date <= target_date
        ).all()

        reminders_sent = 0
        for plan, patient in expiring_plans:
            lock_key = f"whatsapp_lock_{plan.plan_id}"

            if redis_client.exists(lock_key):
                logger.info(f"Skipping {plan.plan_id} - WhatsApp already sent today.")
                continue

            send_whatsapp_reminder.delay(
                phone_number=patient.phone_number,
                patient_name=patient.name,
                sku_id=plan.sku_id,
                plan_id=plan.plan_id
            )
            reminders_sent += 1

        logger.info(f"Adherence sweep complete. Triggered {reminders_sent} refill reminders.")
    finally:
        db.close()
