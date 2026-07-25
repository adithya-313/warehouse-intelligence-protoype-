import urllib.request
import json

url = "http://127.0.0.1:8000/api/v1/knowledge-base/ask"
data = json.dumps({"query": "AMLOK5 side effects"}).encode("utf-8")
req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")

try:
    with urllib.request.urlopen(req) as response:
        print("Status:", response.status)
        print("Body:", response.read().decode("utf-8"))
except urllib.error.HTTPError as e:
    print(f"HTTPError: {e.code}")
    print("Body:", e.read().decode("utf-8"))
except Exception as e:
    print("Error:", e)
