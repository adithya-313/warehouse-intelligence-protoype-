import sys
from sqlalchemy import create_engine, text
from pgvector.sqlalchemy import Vector
from sqlalchemy import bindparam
from sqlalchemy.sql.elements import TextClause

engine = create_engine('postgresql://postgres:postgrespassword@timescaledb:5432/sentinel_db')
with engine.connect() as conn:
    print('Checking AMOXI-500 in clinical_knowledge_base:')
    res = conn.execute(text("SELECT sku_id, metadata_payload, embedding FROM clinical_knowledge_base WHERE sku_id = 'AMOXI-500'")).fetchone()
    if res:
        print(f'Found: {res.sku_id}, metadata: {res.metadata_payload}')
        target_embedding = res.embedding
        print(f"Target embedding type: {type(target_embedding)}, length: {len(target_embedding)}")
    else:
        print('NOT FOUND!')
        sys.exit(1)

    print("\nTesting Query execution:")
    target_sku = 'AMOXI-500'
    threshold = 0.8
    try:
        substitute_query = text("""
            SELECT
                c.sku_id,
                c.metadata_payload ->> 'brand_name' AS brand_name,
                c.metadata_payload ->> 'generic_name' AS generic_class,
                1 - (c.embedding <=> :target_vector) AS matching_score,
                COALESCE(SUM(b.available_quantity), 0) AS stock_qty,
                MIN(b.max_retail_price) AS unit_price_inr
            FROM clinical_knowledge_base c
            JOIN medication_batches b ON c.sku_id = b.sku_id
            WHERE c.sku_id != :original_sku
              AND b.available_quantity > 0
            GROUP BY c.id, c.sku_id, c.metadata_payload, c.embedding
            HAVING (1 - (c.embedding <=> :target_vector)) >= :threshold
            ORDER BY unit_price_inr ASC
        """).bindparams(
            bindparam("target_vector", type_=Vector),
            bindparam("original_sku"),
            bindparam("threshold"),
        )
        print("Query bindparams defined.")
        
        # This is what's running in find_clinical_substitutes:
        substitute_rows = conn.execute(
            substitute_query,
            {
                "target_vector": target_embedding,
                "original_sku": target_sku,
                "threshold": threshold,
            },
        ).fetchall()
        print(f"Success! Found {len(substitute_rows)} substitutes.")
    except Exception as e:
        print(f"Error during execution: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    print("\nTesting Query execution without type_=Vector:")
    try:
        substitute_query = text("""
            SELECT
                c.sku_id,
                c.metadata_payload ->> 'brand_name' AS brand_name,
                c.metadata_payload ->> 'generic_name' AS generic_class,
                1 - (c.embedding <=> :target_vector) AS matching_score,
                COALESCE(SUM(b.available_quantity), 0) AS stock_qty,
                MIN(b.max_retail_price) AS unit_price_inr
            FROM clinical_knowledge_base c
            JOIN medication_batches b ON c.sku_id = b.sku_id
            WHERE c.sku_id != :original_sku
              AND b.available_quantity > 0
            GROUP BY c.id, c.sku_id, c.metadata_payload, c.embedding
            HAVING (1 - (c.embedding <=> :target_vector)) >= :threshold
            ORDER BY unit_price_inr ASC
        """).bindparams(
            bindparam("target_vector"),
            bindparam("original_sku"),
            bindparam("threshold"),
        )
        substitute_rows = conn.execute(
            substitute_query,
            {
                "target_vector": target_embedding,
                "original_sku": target_sku,
                "threshold": threshold,
            },
        ).fetchall()
        print(f"Success without type_! Found {len(substitute_rows)} substitutes.")
    except Exception as e:
        print(f"Error without type_: {type(e).__name__}: {e}")
