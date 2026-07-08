import os
import sys
import datetime
from decimal import Decimal

# Ensure correct module resolution
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from app.infrastructure.database import SessionLocal
    from app.infrastructure.models import MedicationModel, MedicationBatchModel
except ImportError:
    from sentinel_flow_mvp.app.infrastructure.database import SessionLocal
    from sentinel_flow_mvp.app.infrastructure.models import MedicationModel, MedicationBatchModel

def seed_kerala_catalog():
    db = SessionLocal()
    try:
        # Kerala medications data
        medications_data = [
            {
                "sku_id": "DOLO-650",
                "apis": ["Paracetamol"],
                "therapeutic_classes": ["Analgesic", "Antipyretic"],
                "cdsco_schedule": "OTC"
            },
            {
                "sku_id": "ORS-CITRA",
                "apis": ["Oral Rehydration Salts"],
                "therapeutic_classes": ["Electrolytes"],
                "cdsco_schedule": "OTC"
            },
            {
                "sku_id": "CALPOL-250-PEAD",
                "apis": ["Paracetamol"],
                "therapeutic_classes": ["Analgesic", "Antipyretic"],
                "cdsco_schedule": "OTC"
            },
            {
                "sku_id": "PAN-D",
                "apis": ["Pantoprazole", "Domperidone"],
                "therapeutic_classes": ["Antacid", "Antiemetic"],
                "cdsco_schedule": "Schedule H"
            },
            {
                "sku_id": "LARIAGO-250",
                "apis": ["Chloroquine"],
                "therapeutic_classes": ["Antimalarial"],
                "cdsco_schedule": "Schedule H"
            },
            {
                "sku_id": "AUGMENTIN-625",
                "apis": ["Amoxicillin", "Clavulanic Acid"],
                "therapeutic_classes": ["Antibiotic"],
                "cdsco_schedule": "Schedule H"
            },
            {
                "sku_id": "MONTEK-LC",
                "apis": ["Montelukast", "Levocetirizine"],
                "therapeutic_classes": ["Antihistamine", "Antiasthmatic"],
                "cdsco_schedule": "Schedule H"
            },
            {
                "sku_id": "METFORMIN-500",
                "apis": ["Metformin"],
                "therapeutic_classes": ["Antidiabetic"],
                "cdsco_schedule": "Schedule H"
            },
            {
                "sku_id": "TELMA-40",
                "apis": ["Telmisartan"],
                "therapeutic_classes": ["Antihypertensive"],
                "cdsco_schedule": "Schedule H"
            },
            {
                "sku_id": "AZITHRAL-500",
                "apis": ["Azithromycin"],
                "therapeutic_classes": ["Antibiotic"],
                "cdsco_schedule": "Schedule H"
            }
        ]

        # Inserting/merging medications
        for med_data in medications_data:
            existing = db.query(MedicationModel).filter(MedicationModel.sku_id == med_data["sku_id"]).first()
            if existing:
                existing.apis = med_data["apis"]
                existing.therapeutic_classes = med_data["therapeutic_classes"]
                existing.cdsco_schedule = med_data["cdsco_schedule"]
            else:
                med = MedicationModel(**med_data)
                db.add(med)
        db.commit()
        print("Medications seeded/updated successfully.")

        # Kerala medication batches data
        batches_data = [
            {
                "batch_id": "B-DOLO-2027",
                "sku_id": "DOLO-650",
                "expiry_date": datetime.date(2027, 6, 30),
                "cost_price": Decimal("18.50"),
                "max_retail_price": Decimal("30.00"),
                "available_quantity": 150,
                "shelf_location": "SHELF-A1"
            },
            {
                "batch_id": "B-ORS-2028",
                "sku_id": "ORS-CITRA",
                "expiry_date": datetime.date(2028, 4, 15),
                "cost_price": Decimal("12.00"),
                "max_retail_price": Decimal("20.00"),
                "available_quantity": 300,
                "shelf_location": "SHELF-B3"
            },
            {
                "batch_id": "B-CALPOL-2027",
                "sku_id": "CALPOL-250-PEAD",
                "expiry_date": datetime.date(2027, 8, 20),
                "cost_price": Decimal("25.00"),
                "max_retail_price": Decimal("45.00"),
                "available_quantity": 120,
                "shelf_location": "SHELF-A2"
            },
            {
                "batch_id": "B-PAND-2027",
                "sku_id": "PAN-D",
                "expiry_date": datetime.date(2027, 12, 31),
                "cost_price": Decimal("70.00"),
                "max_retail_price": Decimal("120.00"),
                "available_quantity": 80,
                "shelf_location": "SHELF-C1"
            },
            {
                "batch_id": "B-LARIAGO-2027",
                "sku_id": "LARIAGO-250",
                "expiry_date": datetime.date(2027, 10, 15),
                "cost_price": Decimal("45.00"),
                "max_retail_price": Decimal("80.00"),
                "available_quantity": 60,
                "shelf_location": "SHELF-D4"
            },
            {
                "batch_id": "B-AUG-2027",
                "sku_id": "AUGMENTIN-625",
                "expiry_date": datetime.date(2027, 5, 25),
                "cost_price": Decimal("130.00"),
                "max_retail_price": Decimal("200.00"),
                "available_quantity": 90,
                "shelf_location": "SHELF-E2"
            },
            {
                "batch_id": "B-MONTEK-2028",
                "sku_id": "MONTEK-LC",
                "expiry_date": datetime.date(2028, 1, 10),
                "cost_price": Decimal("90.00"),
                "max_retail_price": Decimal("150.00"),
                "available_quantity": 110,
                "shelf_location": "SHELF-F1"
            },
            {
                "batch_id": "B-MET-2028",
                "sku_id": "METFORMIN-500",
                "expiry_date": datetime.date(2028, 9, 30),
                "cost_price": Decimal("12.00"),
                "max_retail_price": Decimal("25.00"),
                "available_quantity": 250,
                "shelf_location": "SHELF-C3"
            },
            {
                "batch_id": "B-TELMA-2027",
                "sku_id": "TELMA-40",
                "expiry_date": datetime.date(2027, 11, 20),
                "cost_price": Decimal("50.00"),
                "max_retail_price": Decimal("90.00"),
                "available_quantity": 140,
                "shelf_location": "SHELF-C4"
            },
            {
                "batch_id": "B-AZI-2027",
                "sku_id": "AZITHRAL-500",
                "expiry_date": datetime.date(2027, 3, 18),
                "cost_price": Decimal("75.00"),
                "max_retail_price": Decimal("120.00"),
                "available_quantity": 100,
                "shelf_location": "SHELF-E4"
            }
        ]

        for batch_data in batches_data:
            existing = db.query(MedicationBatchModel).filter(MedicationBatchModel.batch_id == batch_data["batch_id"]).first()
            if existing:
                existing.sku_id = batch_data["sku_id"]
                existing.expiry_date = batch_data["expiry_date"]
                existing.cost_price = batch_data["cost_price"]
                existing.max_retail_price = batch_data["max_retail_price"]
                existing.available_quantity = batch_data["available_quantity"]
                existing.shelf_location = batch_data["shelf_location"]
            else:
                batch = MedicationBatchModel(**batch_data)
                db.add(batch)
        db.commit()
        print("Medication Batches seeded/updated successfully.")
        print("KERALA CATALOG HYDRATED SUCCESSFULLY.")
    except Exception as e:
        db.rollback()
        print(f"Error seeding Kerala catalog: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    seed_kerala_catalog()
