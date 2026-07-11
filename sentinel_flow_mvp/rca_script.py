import sys
import os

# Ensure the app module can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "postgresql://postgres:postgrespassword@localhost:5432/sentinel_db"

from sqlalchemy import text
from app.infrastructure.database import SessionLocal

def run_keyword_audit(db):
    print("--- 1. Keyword Math Audit ---")
    query = text("SELECT sku_id, ts_rank(content_fts, plainto_tsquery('english', 'is dolo safe?')) AS raw_rank FROM clinical_knowledge_base;")
    result = db.execute(query).fetchall()
    for row in result:
        print(f"SKU: {row.sku_id}, Raw Rank: {row.raw_rank}")

def run_vector_audit():
    print("\n--- 2. Vector Query Audit ---")
    try:
        from app.services.semantic_search import get_embedding_model
        model = get_embedding_model()
        vector = model.encode("is dolo safe?")
        print(f"Vector length: {len(vector)}")
    except Exception as e:
        print(f"Vector Audit Failed: {type(e).__name__} - {e}")

def run_live_simulation(db):
    print("\n--- 3. Live Pipeline Simulation ---")
    try:
        from app.services.semantic_search import execute_clinical_search, _execute_hybrid_search, _calculate_rrf, normalize_vector
        query = "is dolo safe?"
        sku_id = None
        top_k = 3
        
        # Run the internal hybrid search
        raw_results = _execute_hybrid_search(db, query, sku_id)
        
        # Print the scoring for each item
        for item in raw_results:
            # Replicate the RRF calculation just to see the exact values
            print(f"Scoring for SKU: {item['sku_id']}")
            print(item)
    except Exception as e:
        print(f"Live Simulation Failed: {type(e).__name__} - {e}")

if __name__ == "__main__":
    db = SessionLocal()
    try:
        run_keyword_audit(db)
        run_vector_audit()
        run_live_simulation(db)
    finally:
        db.close()
