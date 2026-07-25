from app.infrastructure.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

print("### Task 4 ###")
sql = text("""
    SELECT q.candidate, a.sku_id, a.alias_text, similarity(a.alias_text, q.candidate) AS score
    FROM unnest(CAST(:candidates AS text[])) AS q(candidate)
    JOIN drug_brand_aliases a ON a.alias_text % q.candidate
    ORDER BY score DESC
    LIMIT 3;
""")

res = db.execute(sql, {"candidates": ["domperidone", "dolo 650", "crocin kids"]}).fetchall()
for r in res:
    print(r)
