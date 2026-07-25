from app.infrastructure.database import SessionLocal
from sqlalchemy import text
import json

db = SessionLocal()

print("### Task 1 ###")
res1 = db.execute(text("SELECT sku_id, alias_text, alias_type FROM drug_brand_aliases WHERE alias_text ILIKE '%domperidone%' LIMIT 10;")).fetchall()
for r in res1:
    print(r)

print("\n### Task 2 ###")
res2 = db.execute(text("SELECT sku_id, alias_text, similarity(alias_text, 'can I give domperidone to a 2 year old') AS score FROM drug_brand_aliases ORDER BY score DESC LIMIT 10;")).fetchall()
for r in res2:
    print(r)

print("\n### Task 3 ###")
res3 = db.execute(text("SELECT sku_id, alias_text, similarity(alias_text, 'domperidone') AS score FROM drug_brand_aliases ORDER BY score DESC LIMIT 10;")).fetchall()
for r in res3:
    print(r)
