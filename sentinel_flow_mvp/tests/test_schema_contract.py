import pytest
from sqlalchemy import inspect
from app.infrastructure.database import engine

def test_schema_contract_raw_sql_columns():
    """
    Test that columns queried by raw SQL in knowledge_base.py and drug_resolver.py
    actually exist in the real database schema. This prevents regressions like
    querying for a non-existent 'brand_name' column in medications.
    """
    # 1. Introspect the actual database tables
    from sqlalchemy.exc import OperationalError
    try:
        inspector = inspect(engine)
        if "medications" not in inspector.get_table_names():
            pytest.skip("Real database not available for schema contract test.")
        
        medications_columns = [col['name'] for col in inspector.get_columns("medications")]
        ckb_columns = [col['name'] for col in inspector.get_columns("clinical_knowledge_base")]
    except OperationalError:
        pytest.skip("Real database not available for schema contract test (Connection refused).")

    # 2. Assert columns referenced in drug_resolver.py and knowledge_base.py raw SQL exist
    
    # Referenced in drug_resolver.py: "SELECT sku_id FROM medications WHERE sku_id ILIKE :query LIMIT 1"
    assert "sku_id" in medications_columns, "medications table must have 'sku_id' column"
    
    # Referenced in knowledge_base.py: "SELECT apis[1] FROM medications WHERE sku_id = :sku"
    assert "apis" in medications_columns, "medications table must have 'apis' column"
    
    # Referenced in knowledge_base.py: "SELECT metadata_payload->>'generic_name' FROM clinical_knowledge_base WHERE sku_id = :sku"
    assert "metadata_payload" in ckb_columns, "clinical_knowledge_base table must have 'metadata_payload' column"
    assert "sku_id" in ckb_columns, "clinical_knowledge_base table must have 'sku_id' column"

    # Also assert that 'brand_name' is definitely NOT in medications, ensuring we don't regress
    assert "brand_name" not in medications_columns, "brand_name should not exist in medications"
