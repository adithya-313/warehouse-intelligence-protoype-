import requests
import json

base_url = "http://127.0.0.1:8080"
headers = {"X-Tenant-ID": "PHARM-001"}

queries = [
    {"query": "paracetamol overdose symptoms"},
    {"query": "Augmentin vs Amoxyclav difference"},
    {"query": "tell me about nimesulide dosage"},
    {"query": "is RISO20 safe for a 28 year old pregnant patient?"}, # Known pregnancy contraindication
    {"query": "can I dispense PAN40 to a 45 year old man"} # Normal dispense
]

for q in queries:
    print(f"--- QUERY: {q['query']} ---")
    response = requests.post(f"{base_url}/api/v1/knowledge-base/ask", json=q, headers=headers)
    if response.status_code == 200:
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Error {response.status_code}: {response.text}")
    print("\n")
