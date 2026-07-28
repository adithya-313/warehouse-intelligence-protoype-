"""
Spot-check abemaciclib through the live API after the re-fetch fix.
Uses the same TestClient + API key pattern as the existing test suite.
Correct endpoint: POST /api/v1/knowledge-base/ask
"""
import sys
import os
sys.path.insert(0, "/app")

from fastapi.testclient import TestClient
from app.main import app

API_KEY = "my_super_secret_key_123"
HEADERS = {"X-API-Key": API_KEY}

queries = [
    ("abemaciclib dosage", None),
    ("abemaciclib side effects", None),
    ("abemaciclib contraindications", None),
]

print("\n" + "="*70)
print("SPOT-CHECK: abemaciclib live queries after re-fetch")
print("="*70)

with TestClient(app) as client:
    for q, sku_id in queries:
        print(f"\nQuery: {q!r}")
        body = {"query": q}
        if sku_id:
            body["sku_id"] = sku_id
        resp = client.post(
            "/api/v1/knowledge-base/ask",
            json=body,
            headers=HEADERS,
        )
        if resp.status_code == 200:
            data = resp.json()
            answer = data.get("answer", "(no answer)")
            print(f"  HTTP 200 OK")
            print(f"  Answer (first 500 chars): {answer[:500]}")
            print(f"  Citations: {data.get('citations', [])}")
            print(f"  is_safe_to_dispense: {data.get('is_safe_to_dispense')}")
        else:
            print(f"  HTTP {resp.status_code}: {resp.text[:300]}")

print("\nDone.")
