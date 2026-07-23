import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath('.'))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.domain.drug_resolver import resolve_drug_entity

# Inside Docker, we can use the environment variable
db_url = os.environ.get("DATABASE_URL", "postgresql://postgres:postgrespassword@timescaledb:5432/sentinel_db")
engine = create_engine(db_url)
SessionLocal = sessionmaker(bind=engine)
from app.infrastructure.models import ClinicalKnowledgeBase


def run_regression_test():
    db = SessionLocal()
    
    # Get all 11 rows
    ckb_rows = db.query(ClinicalKnowledgeBase).all()
    test_cases = []
    
    for row in ckb_rows:
        sku = row.sku_id
        payload = row.metadata_payload or {}
        brand = payload.get("brand_name")
        generic = payload.get("generic_name")
        
        if sku: test_cases.append((sku, sku))
        if brand: test_cases.append((brand, sku))
        if generic: test_cases.append((generic, sku))
        
    print(f"Running {len(test_cases)} tests...")
    
    for query, expected_sku in test_cases:
        res = resolve_drug_entity(db, query)
        actual_sku = res.get("sku_id") if res.get("status") == "resolved" else None
        
        match = "MATCH" if actual_sku == expected_sku else f"MISMATCH (Expected: {expected_sku}, Got: {res})"
        print(f"Query: '{query}' -> {match}")
        
    db.close()

if __name__ == "__main__":
    run_regression_test()
