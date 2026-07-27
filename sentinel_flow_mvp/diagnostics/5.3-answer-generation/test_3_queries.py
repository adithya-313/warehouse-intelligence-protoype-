import requests
import time
import json

QUERIES = [
    "paracetamol overdose symptoms",
    "Augmentin vs Amoxyclav difference",
    "tell me about nimesulide dosage"
]

def main():
    for q in QUERIES:
        start = time.time()
        try:
            resp = requests.post("http://localhost:8080/api/v1/knowledge-base/ask", json={"query": q})
            elapsed = time.time() - start
            print(f"QUERY: {q}")
            print(f"TIME: {elapsed:.3f}s")
            print(f"STATUS: {resp.status_code}")
        except Exception as e:
            print(f"ERROR: {e}\n")

if __name__ == "__main__":
    main()
