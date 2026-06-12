"""Quick DB audit: fetch last 10 inventory_count for SKU-NV-5090."""
import sys, os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.infrastructure.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
rows = db.execute(text(
    "SELECT inventory_count FROM inventory_telemetry "
    "WHERE sku_id = 'SKU-NV-5090' ORDER BY recorded_at DESC LIMIT 10"
)).fetchall()
print("Last 10 inventory_count values for SKU-NV-5090:")
print([r[0] for r in rows])
db.close()
