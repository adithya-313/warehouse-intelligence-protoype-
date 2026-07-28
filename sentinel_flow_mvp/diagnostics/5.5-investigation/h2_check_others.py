from app.infrastructure.database import SessionLocal
from app.infrastructure.models import ClinicalKnowledgeBase

db = SessionLocal()
skus = ["GENERIC_REF_IBUPROFEN", "GENERIC_REF_AMOXYCILLIN"]

print("--- HYPOTHESIS 2: OTHER DRUGS CONTENT ---")
for sku in skus:
    med = db.query(ClinicalKnowledgeBase).filter_by(sku_id=sku).first()
    if med:
        print(f"\n[{sku}]")
        print(med.content)
    else:
        print(f"\n[{sku}] Not found.")

db.close()
