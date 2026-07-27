import requests
import time

def run_case(case_name, payload, log_file):
    print(f"Running {case_name}...")
    resp = requests.post("http://localhost:8080/api/v1/knowledge-base/ask", json=payload)
    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.json().get('status', 'no_status')}")
    # We will grep the docker logs for DIAG-H3 and save it to the log_file outside this script

if __name__ == "__main__":
    time.sleep(2)  # ensure api is up
    # Case 1
    run_case("Case 1: raw query", {"query": "paracetamol overdose symptoms"}, "case1.log")
    time.sleep(1)
    
    # Case 2
    run_case("Case 2: normalized string", {"query": "GENERIC_REF_PARACETAMOL overdose symptoms"}, "case2.log")
    time.sleep(1)
    
    # Case 3
    run_case("Case 3: forced sku_id", {"query": "paracetamol overdose symptoms", "sku_id": "GENERIC_REF_PARACETAMOL"}, "case3.log")
    time.sleep(1)
