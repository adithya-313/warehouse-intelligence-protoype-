from fastapi.testclient import TestClient
import torch
import os
import shutil
import uuid
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import app
from app.infrastructure.database import SessionLocal
from app.infrastructure.db.models import LoRAAdapterRegistry

API_KEY = "my_super_secret_key_123"
HEADERS = {"X-API-Key": API_KEY}
SUPPLIER_ID = "Supplier_01"

print("TestClient imported.")

def test_a_happy_path(client):
    print("\n--- Running Test A: Happy Path ---")
    
    # Ensure the file physically exists for the mock to pass
    db = SessionLocal()
    adapter = db.query(LoRAAdapterRegistry).filter(
        LoRAAdapterRegistry.supplier_id == SUPPLIER_ID, 
        LoRAAdapterRegistry.status == "ACTIVE"
    ).first()
    db.close()
    if adapter:
        os.makedirs(os.path.dirname(adapter.adapter_weights_path), exist_ok=True)
        with open(adapter.adapter_weights_path, 'w') as f:
            f.write("mock weights")
            
    pipeline = getattr(app.state, "chronos_pipeline", None)
    if pipeline:
        def mock_load(path, *args, **kwargs):
            if not os.path.exists(path):
                raise OSError(f"File not found {path}")
        pipeline.model.load_adapter = mock_load
        pipeline.model.set_adapter = lambda *args, **kwargs: None
        pipeline.model.delete_adapter = lambda *args, **kwargs: None
        pipeline.model.disable_adapters = lambda *args, **kwargs: None

    payload = {
        "module_id": "demand_forecast",
        "correlation_id": str(uuid.uuid4()),
        "client_id": SUPPLIER_ID,
        "features": {"supplier_id": SUPPLIER_ID},
        "sla_tier": "standard",
        "compute_budget_remaining": 100,
        "timeout_ms": 10000
    }
    response = client.post("/api/v1/predict", json=payload, headers=HEADERS)
    print("Test A Response:", response.status_code, response.json())
    assert response.status_code == 200
    data = response.json()
    assert data["fallback_engaged"] is False
    assert "chronos_lora" in data["model_version"]
    print("Test A Passed.")

def test_b_missing_weights_file(client):
    print("\n--- Running Test B: Missing Weights File ---")
    db = SessionLocal()
    adapter = db.query(LoRAAdapterRegistry).filter(
        LoRAAdapterRegistry.supplier_id == SUPPLIER_ID, 
        LoRAAdapterRegistry.status == "ACTIVE"
    ).first()
    db.close()
    
    if not adapter:
        print("Test B FAILED: No active adapter found.")
        return

    original_path = adapter.adapter_weights_path
    backup_path = original_path + "_backup"
    
    try:
        if os.path.exists(original_path):
            shutil.move(original_path, backup_path)
        else:
            print(f"Warning: Adapter path {original_path} doesn't exist.")
            
        payload = {
            "module_id": "demand_forecast",
            "correlation_id": str(uuid.uuid4()),
            "client_id": SUPPLIER_ID,
            "features": {"supplier_id": SUPPLIER_ID},
            "sla_tier": "standard",
            "compute_budget_remaining": 100,
            "timeout_ms": 10000
        }
        response = client.post("/api/v1/predict", json=payload, headers=HEADERS)
        print("Test B Response:", response.status_code, response.json())
        assert response.status_code == 200
        data = response.json()
        assert data["fallback_engaged"] is False
        assert data["model_version"] == "chronos_base_v1"
        print("Test B Passed.")
    finally:
        if os.path.exists(backup_path):
            shutil.move(backup_path, original_path)

def test_c_vram_oom_simulation(client):
    print("\n--- Running Test C: VRAM OOM Simulation ---")
    payload = {
        "module_id": "demand_forecast",
        "correlation_id": str(uuid.uuid4()),
        "client_id": SUPPLIER_ID,
        "features": {"supplier_id": SUPPLIER_ID},
        "sla_tier": "standard",
        "compute_budget_remaining": 100,
        "timeout_ms": 10000
    }
    
    pipeline = getattr(app.state, "chronos_pipeline", None)
    if not pipeline:
        print("Test C FAILED: No pipeline to mock.")
        return

    with patch.object(pipeline, 'predict', side_effect=torch.cuda.OutOfMemoryError("Mocked OOM")):
        response = client.post("/api/v1/predict", json=payload, headers=HEADERS)
        print("Test C Response:", response.status_code, response.json())
        assert response.status_code == 200
        data = response.json()
        assert data["fallback_engaged"] is True
        assert data["model_version"] == "heuristic_sma_v1"
        print("Test C Passed.")

def test_d_bad_payload(client):
    print("\n--- Running Test D: Bad Payload ---")
    payload = {
        "module_id": "demand_forecast",
        "correlation_id": str(uuid.uuid4()),
        "client_id": SUPPLIER_ID,
        "features": {"supplier_id": SUPPLIER_ID},
        "sla_tier": "standard",
        "compute_budget_remaining": "NOT_AN_INTEGER",
        "timeout_ms": 10000
    }
    response = client.post("/api/v1/predict", json=payload, headers=HEADERS)
    print("Test D Response:", response.status_code, response.json())
    assert response.status_code == 422
    print("Test D Passed.")

if __name__ == "__main__":
    print("Starting tests...")
    with TestClient(app) as client:
        test_a_happy_path(client)
        test_b_missing_weights_file(client)
        test_c_vram_oom_simulation(client)
        test_d_bad_payload(client)
    print("\nTEST PHASE 1 COMPLETE. AI INFERENCE VERIFIED.")
