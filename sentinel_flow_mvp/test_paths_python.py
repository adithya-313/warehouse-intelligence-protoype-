import urllib.request
import urllib.error
import json
import uuid

def send_query(query):
    req = urllib.request.Request(
        "http://localhost:8080/api/v1/knowledge-base/ask",
        data=json.dumps({"query": query}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    print(f"\n--- Query: {query} ---")
    try:
        with urllib.request.urlopen(req) as response:
            print("Response:", json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as e:
        print(f"Error {e.code}: {e.read().decode('utf-8')}")

send_query("hello there")
send_query("Is FAKE-DRUG-99 in stock?")
send_query("Is PAN-40 in stock?")
send_query("What is a substitute for PAN-40?")
send_query("Is PAN-40 safe during pregnancy?")
