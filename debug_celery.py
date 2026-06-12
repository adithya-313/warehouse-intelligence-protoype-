import importlib
import time

start = time.time()
mod = importlib.import_module("app.services.worker_tasks")
print(f"Import took: {time.time()-start:.2f}s")

has_task = hasattr(mod, "predict_forecast_task")
print(f"Has task: {has_task}")

start2 = time.time()
req = {"module_id": "demand_forecast", "supplier_id": "NVIDIA", "sku_id": "TEST", "features": {}, "compute_budget_remaining": 100.0, "timeout_ms": 15000, "sla_tier": "premium"}
task = mod.predict_forecast_task.delay(req)
print(f"Delay took: {time.time()-start2:.2f}s")
print(f"Task id: {task.id}")
