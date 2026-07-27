import psycopg2
DATABASE_URL = "postgresql://postgres:postgrespassword@127.0.0.1:5432/sentinel_db"
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
with conn.cursor() as cur:
    print("Creating GiST index...")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_brand_alias_trgm_gist ON drug_brand_aliases USING GIST (alias_text gist_trgm_ops);")
    print("Done!")
