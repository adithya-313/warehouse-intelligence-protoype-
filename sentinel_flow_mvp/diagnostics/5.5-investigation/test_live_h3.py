import requests

url = "http://127.0.0.1:8000/api/v1/knowledge-base/ask"

def test_query(query: str):
    print(f"\n--- Testing Query: {query} ---")
    resp = requests.post(
        url,
        json={"query": query},
        headers={"x-api-key": "test_dev_key"}
    )
    print(f"Status Code: {resp.status_code}")
    print("Response JSON:")
    print(resp.json())

if __name__ == "__main__":
    test_query("what is amoxicillin used for")
    test_query("tell me about nimesulide dosage")

