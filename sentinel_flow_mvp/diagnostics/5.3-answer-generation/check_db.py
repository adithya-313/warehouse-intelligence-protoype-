import sys
import json
from sqlalchemy import create_engine, text

engine = create_engine("postgresql://postgres:pharmacy_secret@localhost:5432/postgres")
with engine.connect() as conn:
    try:
        res = conn.execute(text("SELECT metadata_payload FROM clinical_knowledge_base WHERE sku_id = 'GENERIC_REF_NIMESULIDE'"))
        print(json.dumps(res.fetchone()[0], indent=2))
    except Exception as e:
        print(f"Error: {e}")
