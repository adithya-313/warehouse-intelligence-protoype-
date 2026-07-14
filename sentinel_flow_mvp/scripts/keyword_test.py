"""Test keyword and vector search directly."""
from app.infrastructure.database import SessionLocal
from app.services.semantic_search import execute_clinical_search

db = SessionLocal()
queries = [
    "isotretinoin for acne in pregnant woman",
    "telmisartan pregnancy",
    "paracetamol fever",
]
for q in queries:
    result = execute_clinical_search(db=db, query=q, top_k=5)
    results = result.get("results", [])
    warning = result.get("safety_warning", "")
    print(f"Query: {q}")
    print(f"  Results: {len(results)}")
    for r in results:
        print(f"    SKU={r['sku_id']}  conf={r['confidence_score']}  content={r['content'][:60]}...")
    if warning:
        print(f"  WARNING: {warning}")
    print()

db.close()
