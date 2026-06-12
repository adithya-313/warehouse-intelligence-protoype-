# RCA 003 — Compound Index Optimization
**Date:** 2026-06-08

## Symptom
DB query latency at 106.51ms — index scan not yet fully optimized for the common access pattern `(supplier_id, sku_id, recorded_at DESC)`.

## Proposed Fix
Apply a dedicated compound index to target index scan:

```sql
CREATE INDEX idx_telemetry_sku_time ON inventory_telemetry (supplier_id, sku_id, recorded_at DESC);
```

## Scope
- **No data aggregation** — preserves 100% accuracy.
- **No schema changes** — pure indexing.
- The index covers the exact columns used in the hot-path query from `scripts/audit_infrastructure.py` and the `DemandForecastingModule` telemetry fetch.
- TimescaleDB hypertable chunk exclusion is preserved because `recorded_at` is the rightmost column; the leading columns (`supplier_id`, `sku_id`) enable efficient chunk pruning when filtering by those dimensions.

## Expected Outcome
- Eliminate the `Merge Append` plan node (from old index `(supplier_id, recorded_at DESC)`).
- Enable a single Index Scan Backward on the compound index.
- Reduce query latency toward sub-50ms for the hot-path 90-day window.
