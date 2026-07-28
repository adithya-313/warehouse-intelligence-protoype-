from sqlalchemy import text
from app.infrastructure.database import SessionLocal

db = SessionLocal()

res = db.execute(text("SELECT content FROM clinical_knowledge_base WHERE sku_id = 'GENERIC_REF_PARACETAMOL'")).scalar()
print("Paracetamol content:")
print(res)
