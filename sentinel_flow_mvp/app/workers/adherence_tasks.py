import logging
import requests
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
        upi_link = f"upi://pay?pa={settings.PHARMACY_UPI_ID}&pn=SentinelPharmacy&cu=INR"

        message_body = (
            f"🏥 *Sentinel Pharmacy*\n\n"
            f"Hi {patient_name},\n"
            f"Your prescription for *{sku_id}* is running low (≤ 3 days remaining).\n\n"
            f"Reply *YES* to confirm home delivery, or click the secure UPI link below to pay and auto-confirm:\n"
            f"👉 {upi_link}\n\n"
            f"Stay healthy!"
        )

        if not settings.META_WHATSAPP_TOKEN or not settings.WHATSAPP_PHONE_ID:
            logger.info(f"🟡 [WHATSAPP MOCK] Keys missing. Mocking delivery to {phone_number}")
            logger.info(f"   Payload: {message_body}")
        else:
            url = f"https://graph.facebook.com/v18.0/{settings.WHATSAPP_PHONE_ID}/messages"
            headers = {
                "Authorization": f"Bearer {settings.META_WHATSAPP_TOKEN}",
                "Content-Type": "application/json"
            }
            payload = {
                "messaging_product": "whatsapp",
                "to": phone_number,
                "type": "text",
                "text": {"body": message_body}
            }

            response = requests.post(url, headers=headers, json=payload, timeout=10)

            if not response.ok:
                raise Exception(f"Meta API Error {response.status_code}: {response.text}")

            logger.info(f"🟢 [WHATSAPP API] Successfully delivered to {phone_number}")

        lock_key = f"whatsapp_lock_{plan_id}"
        redis_client.set(lock_key, "sent", ex=86400)

        return {"status": "delivered", "plan_id": plan_id}

    except Exception as e:
        logger.error(f"WhatsApp delivery failed: {str(e)}")
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))


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
