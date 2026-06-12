# Root Cause Analysis: System Latency Bottlenecks
**Date:** 2026-06-08

## 1. TimescaleDB Latency (107.99 ms)
* **Symptom:** Querying 90 days of inventory telemetry is too slow.
* **Root Cause:** The query planner is consuming ~48ms (almost half the total time) performing a `Merge Append`. The existing index is only on `supplier_id`. The database is forced to sequentially filter `sku_id` across chunks and perform slow Top-N fetches because `recorded_at DESC` is missing from the index tree.
* **Required Fix:** Implement a compound index: `(supplier_id, sku_id, recorded_at DESC)`.

## 2. Redis Latency (88.79 ms)
* **Symptom:** Caching layer is operating at near-disk speeds.
* **Root Cause:** Profiling confirms connection latency is optimal (0.5ms ping). The bottleneck is Network Transport / Bandwidth Saturation. Moving 1MB uncompressed JSON strings across the Redis socket takes ~146ms. 
* **Required Fix:** Implement payload compression (e.g., GZIP or MessagePack) before writing to Redis, or strictly paginate/truncate the cached arrays so we are not transmitting multi-megabyte payloads on every request.
