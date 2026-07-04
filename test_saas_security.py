import urllib.request
import json
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import Tenant, Patient

def run_security_test():
    print("--- INITIATING SAAS SECURITY PENETRATION TEST ---")
    db = SessionLocal()
    
    try:
        # 1. Seed a legitimate Tenant
        test_tenant_id = "PHARM-001"
        if not db.query(Tenant).filter(Tenant.tenant_id == test_tenant_id).first():
            db.add(Tenant(tenant_id=test_tenant_id, name="Test Pharmacy", upi_id="test@upi"))
            db.commit()
            print(f"[OK] Seeded Test Tenant: {test_tenant_id}")

        # 2. The Attack: Try to register a patient but spoof the tenant_id in the payload
        url = "http://localhost:8080/api/v1/patients/register"
        malicious_payload = {
            "patient_id": "PAT-999",
            "name": "John Doe",
            "phone_number": "+919999999999",
            "tenant_id": "HACKER-TENANT" # Attempting to inject data into another pharmacy
        }
        
        # We authenticate as PHARM-001 via the Header
        headers = {
            'Content-Type': 'application/json',
            'X-Tenant-ID': test_tenant_id 
        }
        
        req = urllib.request.Request(url, data=json.dumps(malicious_payload).encode('utf-8'), headers=headers, method='POST')
        
        with urllib.request.urlopen(req) as response:
            print(f"[OK] API Request Successful. Status: {response.status}")

        # 3. The Verification: Did the API block the spoofing attempt?
        patient = db.query(Patient).filter(Patient.patient_id == "PAT-999").first()
        
        if patient.tenant_id == "HACKER-TENANT":
            print("[CRITICAL FAILURE] The API allowed cross-tenant data spoofing!")
        elif patient.tenant_id == test_tenant_id:
            print("[SUCCESS] The API successfully stripped the malicious payload and enforced the Auth Header.")
        else:
            print(f"[UNKNOWN] Patient saved with tenant_id: {patient.tenant_id}")

    except Exception as e:
        print(f"[ERROR] Test failed to execute: {str(e)}")
    finally:
        # Cleanup
        db.query(Patient).filter(Patient.patient_id == "PAT-999").delete()
        db.commit()
        db.close()

if __name__ == "__main__":
    run_security_test()
