import urllib.request
import json
import time

queries = [
    "AMLOK5 side effects",
    "paracetamol overdose symptoms",
    "is metformin safe for someone with kidney problems"
]

url = "http://127.0.0.1:8080/api/v1/knowledge-base/ask"
headers = {"Content-Type": "application/json"}

print("Waiting for server to start...")
for _ in range(30):
    try:
        urllib.request.urlopen("http://127.0.0.1:8080/")
        break
    except urllib.error.HTTPError as e:
        if e.code == 404: # Server is up but root has no route
            break
    except Exception:
        time.sleep(2)
else:
    print("Server did not start in time.")
    exit(1)

print("Server is up, testing queries...")
for q in queries:
    data = json.dumps({"query": q, "sku_id": None}).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as response:
            res_data = response.read().decode("utf-8")
            print(f"Query: {q}\nStatus: {response.status}\nResponse: {res_data}\n{'-'*40}")
    except urllib.error.HTTPError as e:
        print(f"Query: {q}\nError: {e.code} {e.reason}\n{e.read().decode('utf-8')}\n{'-'*40}")
    except Exception as e:
        print(f"Query: {q}\nException: {str(e)}\n{'-'*40}")
