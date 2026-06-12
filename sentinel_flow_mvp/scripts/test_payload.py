"""Test the /api/v1/predict endpoint and capture raw JSON."""
import requests
import json

resp = requests.post(
    "http://localhost:8080/api/v1/predict",
    json={
        "module_id": "demand_forecast",
        "supplier_id": "NVIDIA Corporation",
        "sku_id": "SKU-NV-5090",
        "route_id": "Taiwan -> Kochi Port",
        "compute_budget": 50.0,
    },
    headers={"X-API-Key": "my_super_secret_key_123"},
    timeout=30,
)
print(f"Status: {resp.status_code}")
data = resp.json()
print(f"Keys: {list(data.keys())}")
print(f"prediction_value: {data.get('prediction_value')}")
print(f"historical_trajectory type: {type(data.get('historical_trajectory'))}")
print(f"historical_trajectory length: {len(data.get('historical_trajectory', []))}")
print(f"historical_trajectory[-5:]: {data.get('historical_trajectory', [])[-5:]}")
print(f"forecast_trajectory: {data.get('forecast_trajectory')}")
print(f"\nFull JSON (truncated):")
print(json.dumps(data, indent=2)[:2000])
