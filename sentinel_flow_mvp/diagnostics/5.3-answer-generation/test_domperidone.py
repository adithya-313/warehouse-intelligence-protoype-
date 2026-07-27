import psycopg2
DATABASE_URL = "postgresql://postgres:postgrespassword@127.0.0.1:5432/sentinel_db"
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute("SET pg_trgm.word_similarity_threshold = 0.5;")
    cur.execute("""
        SELECT q.candidate, a.sku_id, a.alias_text, similarity(a.alias_text, q.candidate) AS score
        FROM unnest(CAST(ARRAY['domperidone'] AS text[])) AS q(candidate)
        CROSS JOIN LATERAL (
            SELECT sku_id, alias_text
            FROM drug_brand_aliases
            WHERE q.candidate <% alias_text
            ORDER BY q.candidate <<-> alias_text
            LIMIT 3
        ) a
        ORDER BY score DESC
        LIMIT 3;
    """)
    for row in cur.fetchall():
        print(row)
