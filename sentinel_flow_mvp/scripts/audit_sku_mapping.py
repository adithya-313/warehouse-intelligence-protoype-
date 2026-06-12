import sys
import os
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.infrastructure.database import SessionLocal
from app.infrastructure.models import TelemetryModel

def audit_skus():
    db = SessionLocal()
    try:
        results = db.query(TelemetryModel.supplier_id, TelemetryModel.sku_id).distinct().all()
        mapping = {}
        for supplier_id, sku_id in results:
            if supplier_id not in mapping:
                mapping[supplier_id] = set()
            if sku_id:
                mapping[supplier_id].add(sku_id)
        
        output = [{"supplier_id": k, "known_skus": list(v)} for k, v in mapping.items()]
        print("---AUDIT_START---")
        print(json.dumps(output))
        print("---AUDIT_END---")
    finally:
        db.close()

if __name__ == "__main__":
    audit_skus()
