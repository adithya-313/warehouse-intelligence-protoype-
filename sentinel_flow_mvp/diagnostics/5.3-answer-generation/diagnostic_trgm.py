import psycopg2
import time

DATABASE_URL = "postgresql://postgres:postgrespassword@127.0.0.1:5432/sentinel_db"

def run_query(conn, query):
    with conn.cursor() as cur:
        cur.execute(query)
        try:
            return cur.fetchall()
        except psycopg2.ProgrammingError:
            return None

def main():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    
    print("=== TASK 1: EXPLAIN ANALYZE (Default Threshold) ===")
    plan = run_query(conn, """
        EXPLAIN ANALYZE
        SELECT alias_text, word_similarity('dolo650', alias_text)
        FROM drug_brand_aliases
        WHERE 'dolo650' <% alias_text
        ORDER BY 'dolo650' <<-> alias_text
        LIMIT 20;
    """)
    for row in plan:
        print(row[0])
    
    print("\n=== TASK 2 & 3: Threshold Tuning ===")
    
    # First, get the exact score for DOLO 650 TABLET
    score_res = run_query(conn, "SELECT word_similarity('dolo650', 'DOLO 650 TABLET');")
    exact_score = score_res[0][0]
    print(f"\nExact word_similarity score for 'dolo650' vs 'DOLO 650 TABLET': {exact_score}\n")
    
    for threshold in [0.5, 0.6, 0.7, 0.8]:
        print(f"\n--- Threshold: {threshold} ---")
        run_query(conn, f"SET pg_trgm.word_similarity_threshold = {threshold};")
        
        # EXPLAIN ANALYZE for timing and row count
        plan = run_query(conn, """
            EXPLAIN ANALYZE
            SELECT alias_text, word_similarity('dolo650', alias_text)
            FROM drug_brand_aliases
            WHERE 'dolo650' <% alias_text
            ORDER BY 'dolo650' <<-> alias_text
            LIMIT 20;
        """)
        
        for row in plan:
            print(row[0])
            
    print("\n=== TASK 4: GiST Index Comparison ===")
    print("Creating GiST index...")
    run_query(conn, "CREATE INDEX IF NOT EXISTS idx_brand_alias_trgm_gist ON drug_brand_aliases USING GIST (alias_text gist_trgm_ops);")
    
    run_query(conn, f"SET pg_trgm.word_similarity_threshold = 0.5;")
    print("EXPLAIN ANALYZE with GiST (Threshold 0.5):")
    plan = run_query(conn, """
        EXPLAIN ANALYZE
        SELECT alias_text, word_similarity('dolo650', alias_text)
        FROM drug_brand_aliases
        WHERE 'dolo650' <% alias_text
        ORDER BY 'dolo650' <<-> alias_text
        LIMIT 20;
    """)
    for row in plan:
        print(row[0])
        
    print("\nDropping test GiST index...")
    run_query(conn, "DROP INDEX IF EXISTS idx_brand_alias_trgm_gist;")
    
    conn.close()

if __name__ == "__main__":
    main()
