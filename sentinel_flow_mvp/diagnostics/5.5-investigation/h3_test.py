import requests
import json

base_url = "http://127.0.0.1:8080"
headers = {"X-Tenant-ID": "PHARM-001", "Content-Type": "application/json"}

payload = {"query": "what is amoxicillin used for"}

print("--- HYPOTHESIS 3: API RESPONSE ---")
try:
    response = requests.post(f"{base_url}/api/v1/knowledge-base/ask", json=payload, headers=headers)
    print(f"Status: {response.status_code}")
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    print(f"Error: {e}")
