import requests

url = "http://localhost:8080/api/v1/knowledge-base/ask"
headers = {"Content-Type": "application/json", "X-Tenant-ID": "PHARM-001"}
payload = {"query": "tell me about nimesulide dosage"}

print("Running query: tell me about nimesulide dosage")
try:
    response = requests.post(url, json=payload, headers=headers)
    print(response.json())
except Exception as e:
    print(f"Error: {e}")
