from app.infrastructure.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

candidates = ['domperidone', '2', 'year', 'old', 'domperidone 2', '2 year', 'year old', 'domperidone 2 year', '2 year old']

sql = text("""
    EXPLAIN ANALYZE
    SELECT q.candidate, a.sku_id, a.alias_text, similarity(a.alias_text, q.candidate) AS score
    FROM unnest(CAST(:candidates AS text[])) AS q(candidate)
    JOIN drug_brand_aliases a ON a.alias_text % q.candidate
    ORDER BY score DESC
    LIMIT 3;
""")

print("### EXPLAIN ANALYZE ###")
res = db.execute(sql, {"candidates": candidates}).fetchall()
for r in res:
    print(r[0])
