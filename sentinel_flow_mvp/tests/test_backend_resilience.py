import uuid
import sys
import os

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import app

VALID_API_KEY = "my_super_secret_key_123"

def test_vector_a_bad_token(client):
    print("\n--- Running Vector A: Bruteforce / Bad Token Attack ---")
    
    payload = {
        "module_id": "demand_forecast",
        "correlation_id": str(uuid.uuid4()),
        "client_id": "Supplier_01",
        "features": {"supplier_id": "Supplier_01"},
        "sla_tier": "standard",
        "compute_budget_remaining": 100,
        "timeout_ms": 10000
    }
    
    # Missing header
    response = client.post("/api/v1/predict", json=payload)
    print("No Header POST /api/v1/predict Response Status:", response.status_code)
    assert response.status_code in [401, 403]
    
    # Invalid header
    response = client.post("/api/v1/predict", json=payload, headers={"X-API-Key": "INVALID_KEY"})
    print("Invalid Header POST /api/v1/predict Response Status:", response.status_code)
    assert response.status_code in [401, 403]

    # Test GET /api/v1/suppliers
    response = client.get("/api/v1/suppliers")
    print("No Header GET /api/v1/suppliers Response Status:", response.status_code)
    assert response.status_code in [401, 403]

    print("Vector A Passed.")

def test_vector_b_sql_injection(client):
    print("\n--- Running Vector B: SQL Injection Probing ---")
    sqli_payload = "Supplier_01'; DROP TABLE telemetry;--"
    
    payload = {
        "module_id": "demand_forecast",
        "correlation_id": str(uuid.uuid4()),
        "client_id": sqli_payload,
        "features": {"supplier_id": sqli_payload},
        "sla_tier": "standard",
        "compute_budget_remaining": 100,
        "timeout_ms": 10000
    }
    
    # SQLAlchemy ORM will parameterize this, returning empty results or falling back, not executing DROP.
    response = client.post("/api/v1/predict", json=payload, headers={"X-API-Key": VALID_API_KEY})
    print("SQLi POST Response Status:", response.status_code)
    assert response.status_code == 200
    data = response.json()
    assert data["fallback_engaged"] is True
    
    # Test GET with SQLi
    response = client.get(f"/api/v1/suppliers?supplier_id={sqli_payload}", headers={"X-API-Key": VALID_API_KEY})
    print("SQLi GET Response Status:", response.status_code)
    assert response.status_code in [200, 422]
    
    print("Vector B Passed.")

def test_vector_c_missing_supplier(client):
    print("\n--- Running Vector C: Missing Supplier Records ---")
    payload = {
        "module_id": "demand_forecast",
        "correlation_id": str(uuid.uuid4()),
        "client_id": "SUPPLIER_DOES_NOT_EXIST",
        "features": {"supplier_id": "SUPPLIER_DOES_NOT_EXIST"},
        "sla_tier": "standard",
        "compute_budget_remaining": 100,
        "timeout_ms": 10000
    }
    
    # Should gracefully catch empty telemetry and engage heuristic fallback
    response = client.post("/api/v1/predict", json=payload, headers={"X-API-Key": VALID_API_KEY})
    print("Missing Supplier Response Status:", response.status_code)
    assert response.status_code == 200
    data = response.json()
    assert data["fallback_engaged"] is True
    assert data["model_version"] == "heuristic_sma_v1"
    
    print("Vector C Passed.")

def test_vector_d_payload_fuzzing(client):
    print("\n--- Running Vector D: Payload Boundary Fuzzing ---")
    
    # Sending wrong types to trigger Pydantic 422 validation
    payload_bad_type = {
        "module_id": "demand_forecast",
        "correlation_id": str(uuid.uuid4()),
        "client_id": "Supplier_01",
        "features": "Not a dict, this is a string",
        "sla_tier": "standard",
        "compute_budget_remaining": "NOT_AN_INT",
        "timeout_ms": "NOT_AN_INT"
    }
    response_bad = client.post("/api/v1/predict", json=payload_bad_type, headers={"X-API-Key": VALID_API_KEY})
    print("Bad Types Payload Status:", response_bad.status_code)
    assert response_bad.status_code == 422
    
    # Massive payload
    massive_string = "X" * (1024 * 512) # 512KB string
    payload_massive = {
        "module_id": "demand_forecast",
        "correlation_id": str(uuid.uuid4()),
        "client_id": "Supplier_01",
        "features": {"huge_key": massive_string},
        "sla_tier": "standard",
        "compute_budget_remaining": 100,
        "timeout_ms": 10000
    }
    response_massive = client.post("/api/v1/predict", json=payload_massive, headers={"X-API-Key": VALID_API_KEY})
    print("Massive Payload Status:", response_massive.status_code)
    assert response_massive.status_code in [200, 413, 422]
    
    print("Vector D Passed.")

if __name__ == "__main__":
    print("Starting Resilience Tests...")
    
    # Use TestClient context manager to properly trigger startup/shutdown events
    with TestClient(app) as client:
        test_vector_a_bad_token(client)
        test_vector_b_sql_injection(client)
        test_vector_c_missing_supplier(client)
        test_vector_d_payload_fuzzing(client)
        
    print("\nTEST PHASE 2 COMPLETE. SECURITY & DB BOUNDARIES HARDENED.")
