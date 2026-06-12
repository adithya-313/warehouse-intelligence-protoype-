import time
import json
import os
import gzip
import psutil
import redis
from sqlalchemy import text
from app.infrastructure.database import SessionLocal

def run_audit():
    results = {}
    
    # 3. API Container Memory Profiling
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    results['memory_mb'] = mem_info.rss / (1024 * 1024)
    
    # 1. TimescaleDB Integrity & Performance
    db = SessionLocal()
    try:
        start_time = time.perf_counter()
        query = text("SELECT * FROM inventory_telemetry WHERE supplier_id='NVIDIA' AND sku_id='SKU-NV-5090' ORDER BY recorded_at DESC LIMIT 90")
        db.execute(query).fetchall()
        db_latency = (time.perf_counter() - start_time) * 1000
        results['db_latency_ms'] = db_latency
        
        # Check hypertable status
        ht_query = text("SELECT count(*) FROM _timescaledb_catalog.hypertable WHERE table_name = 'inventory_telemetry'")
        ht_count = db.execute(ht_query).scalar()
        results['hypertable_status'] = bool(ht_count and ht_count > 0)
    except Exception as e:
        results['db_latency_ms'] = -1
        results['hypertable_status'] = False
        print(f"DB Error: {e}")
    finally:
        db.close()
        
    # 2. Redis Cache Verification (GZIP compressed)
    try:
        r = redis.Redis(host='redis', port=6379, db=0, socket_timeout=2.0)
        payload = json.dumps({"data": "x" * (1024 * 1024)}).encode()
        compressed = gzip.compress(payload)
        start_time = time.perf_counter()
        r.set('audit_test_key', compressed)
        fetched_compressed = r.get('audit_test_key')
        if fetched_compressed:
            _ = json.loads(gzip.decompress(fetched_compressed).decode())
        r.delete('audit_test_key')
        redis_latency = (time.perf_counter() - start_time) * 1000
        results['redis_latency_ms'] = redis_latency
    except Exception as e:
        results['redis_latency_ms'] = -1
        print(f"FATAL: Redis caching layer is down. Error: {e}")
        
    print("\n--- AUDIT_OUTPUT_START ---")
    print(f"DB_LATENCY|{results.get('db_latency_ms', -1):.2f}")
    print(f"HYPERTABLE|{results.get('hypertable_status', False)}")
    print(f"REDIS_LATENCY|{results.get('redis_latency_ms', -1):.2f}")
    print(f"MEMORY|{results.get('memory_mb', -1):.2f}")
    print("--- AUDIT_OUTPUT_END ---")

if __name__ == "__main__":
    run_audit()
