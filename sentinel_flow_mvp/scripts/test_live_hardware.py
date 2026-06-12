import urllib.request
import urllib.error
import json
import sys

url = 'http://localhost:8080/api/v1/predict'
headers = {
    'Content-Type': 'application/json',
    'X-API-Key': 'my_super_secret_key_123'
}
data = {
    "module_id": "demand_forecast",
    "supplier_id": "NVIDIA Corporation",
    "sku_id": "SKU-NV-5090",
    "route_id": "Taiwan -> Kochi Port",
    "compute_budget": 50.0
}

req = urllib.request.Request(url, json.dumps(data).encode('utf-8'), headers)

try:
    with urllib.request.urlopen(req) as response:
        res_data = json.loads(response.read().decode('utf-8'))
        print("Response JSON:")
        print(json.dumps(res_data, indent=2))
        
        if res_data.get('fallback_engaged'):
            print("\nFALLBACK ENGAGED. Investigate API logs!")
        else:
            print("\nSUCCESS: Primary ML model executed successfully.")
except urllib.error.HTTPError as e:
    print(f"HTTPError: {e.code} {e.reason}")
    print(e.read().decode('utf-8'))
except Exception as e:
    print(f"Error: {e}")
