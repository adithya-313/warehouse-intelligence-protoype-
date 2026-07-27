from fastapi.testclient import TestClient
from app.main import create_application
from app.core.config import get_application_settings

app = create_application()
client = TestClient(app)

def test_query(query: str):
    print(f"\n--- Testing Query: {query} ---")
    resp = client.post(
        "/api/v1/knowledge-base/ask",
        json={"query": query},
        headers={"x-api-key": "dev_super_secret_admin_key_999"}
    )
    print(f"Status Code: {resp.status_code}")
    print("Response JSON:")
    print(resp.json())

if __name__ == "__main__":
    test_query("what is amoxicillin used for")
    test_query("tell me about nimesulide dosage")
