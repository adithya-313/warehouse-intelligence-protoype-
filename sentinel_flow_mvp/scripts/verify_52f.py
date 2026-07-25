import logging
import json
import time
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session
from app.infrastructure.database import SessionLocal
from sentence_transformers import SentenceTransformer
import torch

def get_explain_analyze(db, query):
    explain_query = "EXPLAIN ANALYZE " + query
    result = db.execute(sa_text(explain_query)).fetchall()
    return "\n".join([row[0] for row in result])

def main():
    print("=== TASK 1: Vector search performance ===")
    
    # Generate a dummy 768-d vector to avoid slow SentenceTransformer loading
    query_vector = [0.01] * 768
    
    db = SessionLocal()
    
    vector_sql = f"""
        SELECT sku_id, embedding <=> '{str(query_vector)}'::vector AS distance
        FROM clinical_knowledge_base
        ORDER BY embedding <=> '{str(query_vector)}'::vector
        LIMIT 10;
    """
    
    plan1 = get_explain_analyze(db, vector_sql)
    print(plan1)
    
    print("\n=== TASK 2: Brand-alias resolver performance ===")
    
    for input_term in ["DOLO650", "CROCIN", "CALPOL65O"]:
        print(f"\n--- Testing query: {input_term} ---")
        # Replace single quotes in string to avoid SQL injection
        safe_term = input_term.replace("'", "''")
        alias_sql = f"""
            SELECT sku_id, alias_text, similarity(alias_text, '{safe_term}') AS score
            FROM drug_brand_aliases
            WHERE alias_text % '{safe_term}'
            ORDER BY score DESC
            LIMIT 3;
        """
        plan2 = get_explain_analyze(db, alias_sql)
        print(plan2)
    
    print("\n=== TASK 4: Data integrity ===")
    empty_content_sql = "SELECT COUNT(*) FROM clinical_knowledge_base WHERE content IS NULL OR content = '';"
    empty_content_count = db.execute(sa_text(empty_content_sql)).scalar()
    print(f"Empty content rows: {empty_content_count}")
    
    null_embedding_sql = "SELECT COUNT(*) FROM clinical_knowledge_base WHERE embedding IS NULL;"
    null_embedding_count = db.execute(sa_text(null_embedding_sql)).scalar()
    print(f"Null embedding rows: {null_embedding_count}")
    
    spot_check_sql = f"""
        SELECT sku_id, content
        FROM clinical_knowledge_base 
        WHERE sku_id LIKE 'GENERIC_REF_%' 
        ORDER BY RANDOM() LIMIT 3;
    """
    spot_check = db.execute(sa_text(spot_check_sql)).fetchall()
    
    print("\n--- Spot check ---")
    for row in spot_check:
        sku = row[0]
        content = row[1][:100].replace("\n", " ") + "..."
        print(f"SKU: {sku}")
        print(f"Content: {content}")
        
        # Test if embedding represents the content by encoding it and comparing distance to its own embedding
        # Skipped exact embedding distance comparison to avoid loading model
        pass
        
        # Skipped exact embedding distance comparison to avoid loading model
        pass
        
    db.close()

if __name__ == "__main__":
    main()
