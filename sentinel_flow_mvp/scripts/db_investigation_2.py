from app.infrastructure.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

print("### Task 3 ###")
res = db.execute(text("SELECT AVG(array_length(string_to_array(alias_text, ' '), 1)) AS avg_word_count, MAX(array_length(string_to_array(alias_text, ' '), 1)) AS max_word_count FROM drug_brand_aliases;")).fetchone()
print(res)
