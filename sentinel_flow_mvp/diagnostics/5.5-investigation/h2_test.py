from app.infrastructure.database import SessionLocal
from app.infrastructure.models import ClinicalKnowledgeBase

db = SessionLocal()
med = db.query(ClinicalKnowledgeBase).filter_by(sku_id="GENERIC_REF_PARACETAMOL").first()

print("--- HYPOTHESIS 2: PARACETAMOL ALL FIELDS ---")
if med:
    print(f"content: {med.content}")
    print(f"pregnancy_category: {med.pregnancy_category}")
    print(f"pediatric_age_threshold_months: {med.pediatric_age_threshold_months}")
else:
    print("Not found.")

db.close()
