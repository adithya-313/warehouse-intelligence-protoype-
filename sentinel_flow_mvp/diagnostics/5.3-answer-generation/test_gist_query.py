import psycopg2
DATABASE_URL = "postgresql://postgres:postgrespassword@127.0.0.1:5432/sentinel_db"
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute("SET pg_trgm.word_similarity_threshold = 0.5;")
    cur.execute("""
        EXPLAIN ANALYZE
        SELECT q.candidate, a.sku_id, a.alias_text, word_similarity(q.candidate, a.alias_text) AS score
        FROM unnest(CAST(ARRAY['dolo650', 'crocin'] AS text[])) AS q(candidate)
        JOIN drug_brand_aliases a ON q.candidate <% a.alias_text
        ORDER BY q.candidate <<-> a.alias_text
        LIMIT 3;
    """)
    for row in cur.fetchall():
        print(row[0])
