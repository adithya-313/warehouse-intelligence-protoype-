import httpx
import time
import json
import logging
import re
from httpx import ReadTimeout, ConnectError

# We need to know which SKU matched. Since we don't have direct access to the app logs here,
# we can fetch the app logs after running each query or parse the answer. 
# But wait, the best way to get logs for each query is to run the query, then fetch the latest logs.
# Actually, the user says "if visible in logs (helps us verify it found the RIGHT drug)". 
# Let's just run them, and then I will manually check the docker compose logs for the API.

QUERIES = [
    "is Dolo650 safe for a pregnant woman",
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

def run_spot_checks():
    results = []
    
    # Let's clear the API logs if we can, or just track timestamps
    
    with httpx.Client(base_url="http://localhost:8080", timeout=60.0) as client:
        for i, q in enumerate(QUERIES, 1):
            start = time.time()
            error = "none"
            raw_response = ""
            try:
                # Based on standard routing from app/api/v1/knowledge_base.py
                resp = client.post("/api/v1/knowledge-base/ask", json={"query": q, "sku_id": None})
                resp.raise_for_status()
                data = resp.json()
                raw_response = json.dumps(data, indent=2)
                # Or just print the text of the answer
                if "answer" in data:
                    raw_response = data["answer"]
                else:
                    raw_response = json.dumps(data)
            except Exception as e:
                error = str(e)
                if hasattr(e, 'response') and e.response is not None:
                    raw_response = e.response.text
                
            elapsed = time.time() - start
            
            results.append({
                "id": i,
                "query": q,
                "raw_response": raw_response,
                "time": f"{elapsed:.2f}s",
                "error": error
            })
            
    with open("spot_check_results.json", "w") as f:
        json.dump(results, f, indent=2)

if __name__ == "__main__":
    run_spot_checks()
