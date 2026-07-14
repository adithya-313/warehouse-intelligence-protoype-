"""Test Rule Engine blocking via live API."""
import urllib.request, json

BASE = "http://localhost:8080/api/v1/knowledge-base/ask"

tests = [
    ("Telmisartan pregnancy (Cat D, should BLOCK)", {"query": "telmisartan pregnancy", "top_k": 3}),
    ("Paracetamol fever (Cat B, should ALLOW)", {"query": "paracetamol fever", "top_k": 3}),
]

for label, body in tests:
    data = json.dumps(body).encode()
    req = urllib.request.Request(BASE, data=data, headers={"Content-Type": "application/json"})
    resp = urllib.request.urlopen(req)
    r = json.loads(resp.read().decode())
    verdict = "BLOCK" if not r["is_safe_to_dispense"] else "ALLOW"
    print(f"[{verdict}] {label}")
    print(f"         answer: {r['answer'][:120]}")
    print(f"         safe: {r['is_safe_to_dispense']}  lock: {r['system_lock_reason']}")
    print(f"         context: {len(r['context_used'])} items")
    for c in r.get("context_used", []):
        print(f"           SKU={c.get('sku_id','?')} conf={c.get('confidence_score','?')}")
    print()
