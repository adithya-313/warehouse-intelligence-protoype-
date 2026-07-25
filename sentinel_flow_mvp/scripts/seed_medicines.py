"""
Seeds 20 essential medicines into the medications table.
Upsert-safe: skips any SKU that already exists.
"""

from app.infrastructure.database import SessionLocal
from app.infrastructure.models import MedicationModel

# 20 essential medicines with API names and regulatory schedules
MEDICINES = [
    {"sku_id": "AMOX500",  "api": "Amoxicillin",       "schedule": "Schedule H"},
    {"sku_id": "PAN40",    "api": "Pantoprazole",       "schedule": "OTC"},
    {"sku_id": "AZITH500", "api": "Azithromycin",       "schedule": "Schedule H"},
    {"sku_id": "CALPOL650","api": "Paracetamol",        "schedule": "OTC"},
    {"sku_id": "TELMA40",  "api": "Telmisartan",        "schedule": "OTC"},
    {"sku_id": "MET500",   "api": "Metformin",          "schedule": "OTC"},
    {"sku_id": "ASP75",    "api": "Aspirin",            "schedule": "OTC"},
    {"sku_id": "CET10",    "api": "Cetirizine",         "schedule": "OTC"},
    {"sku_id": "DOM10",    "api": "Domperidone",        "schedule": "OTC"},
    {"sku_id": "IBU400",   "api": "Ibuprofen",          "schedule": "OTC"},
    {"sku_id": "VITD3",    "api": "Cholecalciferol",    "schedule": "OTC"},
    {"sku_id": "AML5",     "api": "Amlodipine",         "schedule": "OTC"},
    {"sku_id": "ATOR10",   "api": "Atorvastatin",       "schedule": "OTC"},
    {"sku_id": "GLIM2",    "api": "Glimepiride",        "schedule": "OTC"},
    {"sku_id": "VITB12",   "api": "Methylcobalamin",    "schedule": "OTC"},
    {"sku_id": "ROSU10",   "api": "Rosuvastatin",       "schedule": "OTC"},
    {"sku_id": "MONT10",   "api": "Montelukast",        "schedule": "OTC"},
    {"sku_id": "FURO40",   "api": "Furosemide",         "schedule": "Schedule H"},
    {"sku_id": "CLOP75",   "api": "Clopidogrel",       "schedule": "OTC"},
    {"sku_id": "LOS50",    "api": "Losartan",           "schedule": "OTC"},
]

db = SessionLocal()
try:
    count = 0
    for med in MEDICINES:
        existing = db.query(MedicationModel).filter_by(sku_id=med["sku_id"]).first()
        if existing:
            continue
        db.add(MedicationModel(
            sku_id=med["sku_id"],
            apis=[med["api"]],
            therapeutic_classes=["General Medicine"],
            cdsco_schedule=med["schedule"],
            is_approved_by_curator=True,
        ))
        count += 1
    db.commit()
    print(f"Seeded {count} new medicines (skipped {len(MEDICINES) - count} existing).")
except Exception as e:
    db.rollback()
    print(f"Error: {e}")
    raise
finally:
    db.close()
