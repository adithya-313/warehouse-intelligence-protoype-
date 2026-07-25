import requests
import json
import time

queries = [
    "is dolo650 safe for a pregnant woman",
    "waht is teh dose of crocin for kids",
    "can I give domperidone to a 2 year old",
    "AMLOK5 side effects",
    "is amoxycillin safe with alcohol",
    "what is abemaciclib used for",
    "tell me about nimesulide dosage",
    "Augmentin vs Amoxyclav difference",
    "paracetamol overdose symptoms",
    "is metformin safe for someone with kidney problems"
]

print("### Task 6: 10-query Spot Check ###")
for q in queries:
    t0 = time.time()
    try:
        res = requests.post("http://localhost:8080/api/v1/knowledge-base/ask", json={"query": q, "sku_id": None}, timeout=30)
        t1 = time.time()
        print(f"\nQuery: {q}")
        print(f"Time: {(t1 - t0) * 1000:.2f}ms")
        if res.status_code == 200:
            data = res.json()
            print(f"Answer: {data.get('answer', 'N/A')}")
            # If the response includes the sku used or citations, we can print it
            citations = data.get("citations", [])
            skus = set(c.get("sku_id") for c in citations if c.get("sku_id"))
            print(f"Matched SKUs in citations: {list(skus)}")
        else:
            print(f"Error {res.status_code}: {res.text}")
    except Exception as e:
        print(f"\nQuery: {q}")
        print(f"Crash: {e}")
