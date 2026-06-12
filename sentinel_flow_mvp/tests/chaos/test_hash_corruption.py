import sys
import os
import requests
import json
import time

# Add the project root to sys.path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.infrastructure.database import SessionLocal
from app.infrastructure.db.models import LoRAAdapterRegistry

API_URL = "http://localhost:8080/api/v1/predict"

def sabotage_adapter():
    session = SessionLocal()
    try:
        # Find an active adapter
        adapter = session.query(LoRAAdapterRegistry).filter(
            LoRAAdapterRegistry.status == "ACTIVE",
            LoRAAdapterRegistry.adapter_weights_path.isnot(None)
        ).first()
        
        if not adapter:
            print("No active adapter found to sabotage! Creating a fake one...")
            # First clean up any existing sabotage_test_adapter
            existing = session.query(LoRAAdapterRegistry).filter_by(id="sabotage_test_adapter").first()
            if existing:
                session.delete(existing)
                session.commit()
                
            adapter = LoRAAdapterRegistry(
                id="sabotage_test_adapter",
                module_name="demand_forecast",
                supplier_id="NVIDIA Corporation",
                base_model_version="chronos_base_v1",
                adapter_weights_path="/tmp/fake_adapter",
                checksum="fake_checksum",
                status="ACTIVE"
            )
            session.add(adapter)
            session.commit()
            
            os.makedirs("/tmp/fake_adapter", exist_ok=True)
            safetensors_path = "/tmp/fake_adapter/adapter_model.safetensors"
            with open(safetensors_path, "wb") as f:
                f.write(b"dummy data")
        else:
            safetensors_path = os.path.join(adapter.adapter_weights_path, "adapter_model.safetensors")
            if not os.path.exists(safetensors_path):
                print(f"File not found: {safetensors_path}, creating a dummy one for the test.")
                os.makedirs(adapter.adapter_weights_path, exist_ok=True)
                with open(safetensors_path, "wb") as f:
                    f.write(b"dummy data")
        
        print(f"Sabotaging file: {safetensors_path}")
        # Read the file
        with open(safetensors_path, "rb") as f:
            data = bytearray(f.read())
            
        if len(data) == 0:
            data = bytearray(b"some data")
            
        # Corrupt 1 byte
        data[0] = data[0] ^ 0xFF
        
        # Write it back
        with open(safetensors_path, "wb") as f:
            f.write(data)
            
        print("File sabotaged successfully.")
        
        # Now fire inference request
        print(f"Firing inference request for supplier: {adapter.supplier_id}")
        payload = {
            "module_id": "demand_forecast",
            "supplier_id": adapter.supplier_id,
            "sku_id": "SKU-NV-4070S",
            "route_id": "route_001",
            "features": {"historical_sales": [1, 2, 3]},
            "sla_tier": "premium",
            "compute_budget_remaining": 50.0
        }
        
        response = requests.post(
            API_URL, 
            json=payload, 
            headers={"X-API-Key": "my_super_secret_key_123", "Content-Type": "application/json"}
        )
        print(f"API Response Status: {response.status_code}")
        response_json = response.json()
        print(f"API Response Body: {json.dumps(response_json, indent=2)}")
        
        if response.status_code == 202:
            task_id = response_json.get("task_id")
            print(f"Polling task {task_id}...")
            while True:
                task_resp = requests.get(f"http://localhost:8080/api/v1/tasks/{task_id}", headers={"X-API-Key": "my_super_secret_key_123"})
                task_data = task_resp.json()
                if task_data.get("status") == "SUCCESS":
                    response_json = task_data.get("result", {})
                    break
                elif task_data.get("status") in ["FAILURE", "REVOKED"]:
                    print("Task failed:", task_data)
                    break
                time.sleep(0.5)
        
        if response_json.get("model_version") == "chronos_base_v1" or response_json.get("fallback_engaged") == True:
            print("SUCCESS: System successfully fell back to base model!")
        else:
            print("FAILED: System did not handle corruption properly. Response:", json.dumps(response_json, indent=2))
            
    finally:
        session.close()

if __name__ == "__main__":
    sabotage_adapter()
