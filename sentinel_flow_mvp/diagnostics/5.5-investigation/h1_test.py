import logging
from app.infrastructure.database import SessionLocal
from app.domain.drug_resolver import resolve_drug_entity

# Configure logging to print everything
logging.basicConfig(level=logging.INFO, format="%(message)s")

db = SessionLocal()

queries = [
    "pantoprazole side effects",
    "ibuprofen side effects",
    "amoxicillin side effects"
]

print("--- HYPOTHESIS 1 TESTS ---")
for q in queries:
    print(f"\n[QUERY]: {q}")
    res = resolve_drug_entity(db, q)
    print(f"[RESULT]: {res}")

db.close()
