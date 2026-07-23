import psycopg2
import os

db_url = os.environ.get("DATABASE_URL", "postgresql://postgres:postgrespassword@timescaledb:5432/sentinel_db")
conn = psycopg2.connect(db_url)
cur = conn.cursor()

print("--- 3. Backfilling rows ---")
cur.execute("SELECT sku_id, metadata_payload FROM clinical_knowledge_base;")
rows = cur.fetchall()

insert_count = 0
for row in rows:
    sku_id = row[0]
    payload = row[1] or {}
    
    brand_name = payload.get("brand_name")
    generic_name = payload.get("generic_name")
    
    if brand_name:
        cur.execute("""
            INSERT INTO drug_brand_aliases (sku_id, alias_text, alias_type)
            VALUES (%s, %s, 'brand_name');
        """, (sku_id, brand_name.upper()))
        insert_count += 1
        
    if generic_name:
        cur.execute("""
            INSERT INTO drug_brand_aliases (sku_id, alias_text, alias_type)
            VALUES (%s, %s, 'generic_name');
        """, (sku_id, generic_name.upper()))
        insert_count += 1
        
conn.commit()
print(f"Rows inserted: {insert_count}")

print("\n--- 4. Checking sample rows ---")
cur.execute("SELECT * FROM drug_brand_aliases LIMIT 3;")
samples = cur.fetchall()
for s in samples:
    print(s)

conn.close()
