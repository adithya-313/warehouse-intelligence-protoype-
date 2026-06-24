import urllib.request
import urllib.error
import json

url = "http://localhost:8080/api/v1/knowledge-base/ask"
payload = json.dumps({
    "query": "Is Dolo-650 safe?",
    "top_k": 3
}).encode('utf-8')

headers = {'Content-Type': 'application/json'}
req = urllib.request.Request(url, data=payload, headers=headers, method='POST')

print("--- DIAGNOSTIC PROBE INITIATED ---")
try:
    with urllib.request.urlopen(req) as response:
        print(f"STATUS: {response.status}")
        print(f"RESPONSE: {response.read().decode('utf-8')}")
except urllib.error.HTTPError as e:
    print(f"HTTP ERROR: {e.code}")
    print(f"ERROR BODY: {e.read().decode('utf-8')}")
except urllib.error.URLError as e:
    print(f"CONNECTION ERROR: {e.reason}")
    print("The backend server is either not running on port 8080, or it crashed.")
