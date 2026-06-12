import json
import requests
import time

def test_unified_stockout():
    url = "http://localhost:8080/api/v1/predict"
    payload = {
        "module_id": "stockout_prediction",
        "supplier_id": "NVIDIA Corporation",
        "sku_id": "SKU-NV-AI900",
        "route_id": "route_1",
        "compute_budget": 50.0,
        "current_inventory": 100,
        "lead_time_days": 10
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": "my_super_secret_key_123"
    }
    
    print(f"Sending request to {url}")
    response = requests.post(url, json=payload, headers=headers)
    print(f"Response: {response.status_code}")
    print(response.json())
    
    if response.status_code == 202:
        task_id = response.json()["task_id"]
        status_url = f"http://localhost:8080/api/v1/tasks/{task_id}"
        print(f"Polling task status at {status_url}")
        
        for _ in range(60):
            status_resp = requests.get(status_url, headers=headers)
            status_data = status_resp.json()
            if status_data.get("status") == "SUCCESS":
                print("\n=== REAL CHRONOS STOCKOUT OUTPUT ===")
                print(json.dumps(status_data["result"], indent=2))
                break
            elif status_data.get("status") in ["FAILURE", "REVOKED"]:
                print(f"\nFAILED: {status_data}")
                break
            print(f"...waiting ({status_data.get('status')})")
            time.sleep(2)
        else:
            print("Timeout waiting for task")

if __name__ == "__main__":
    test_unified_stockout()
