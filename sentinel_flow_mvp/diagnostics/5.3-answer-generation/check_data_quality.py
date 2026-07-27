from app.infrastructure.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

# We want to check if data_quality is populated in metadata_payload
query = text("""
    SELECT 
        COUNT(*) as total_records,
        SUM(CASE WHEN metadata_payload->>'data_quality' IS NOT NULL THEN 1 ELSE 0 END) as populated,
        SUM(CASE WHEN metadata_payload->>'data_quality' IS NULL THEN 1 ELSE 0 END) as missing,
        SUM(CASE WHEN metadata_payload->>'data_quality' = 'identity_only' THEN 1 ELSE 0 END) as identity_only_count,
        SUM(CASE WHEN metadata_payload->>'data_quality' = 'full' THEN 1 ELSE 0 END) as full_count
    FROM clinical_knowledge_base
    WHERE metadata_payload->>'source' = 'openfda_generic_reference'
""")

result = db.execute(query).fetchone()

print(f"Total Generic Reference Records: {result.total_records}")
print(f"Populated data_quality: {result.populated}")
print(f"Missing data_quality: {result.missing}")
print(f"Count of 'identity_only': {result.identity_only_count}")
print(f"Count of 'full': {result.full_count}")
