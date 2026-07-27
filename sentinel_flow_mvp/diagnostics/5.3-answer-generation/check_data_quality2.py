from app.infrastructure.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

query = text("""
    SELECT 
        metadata_payload->>'data_quality' as dq,
        COUNT(*) as count
    FROM clinical_knowledge_base
    WHERE metadata_payload->>'source' = 'openfda_generic_reference'
    GROUP BY metadata_payload->>'data_quality'
""")

results = db.execute(query).fetchall()

for row in results:
    print(f"Value: {row.dq} | Count: {row.count}")
