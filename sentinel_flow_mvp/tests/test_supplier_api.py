"""
End-to-end tests for the Supplier API (GET and POST /api/v1/suppliers).
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import MagicMock
from sqlalchemy.orm import Session
from app.api.supplier_router import router as supplier_router
from app.infrastructure.database import get_database_session
from app.infrastructure.models import SupplierModel

# Create an in-memory list to act as our "database" for these tests
fake_db = []

app = FastAPI()
app.include_router(supplier_router, prefix="/api/v1/suppliers")

def get_stateful_mock_db():
    """
    Creates a mock SQLAlchemy session that uses our fake_db list.
    This allows us to test POST followed by GET within the same test.
    """
    session = MagicMock(spec=Session)
    
    # Mock POST (add supplier)
    def mock_add(instance):
        if isinstance(instance, SupplierModel):
            fake_db.append(instance)
    session.add.side_effect = mock_add
    
    # Mock GET (query suppliers)
    mock_query = MagicMock()
    
    # .count() returns length of fake_db
    mock_query.count.side_effect = lambda: len(fake_db)
    
    # For pagination .offset(X).limit(Y).all()
    mock_offset = MagicMock()
    mock_limit = MagicMock()
    
    state = {"offset": 0, "limit": 50}
    
    def set_offset(val):
        state["offset"] = val
        return mock_offset
        
    def set_limit(val):
        state["limit"] = val
        return mock_limit
        
    def mock_all():
        start = state["offset"]
        end = start + state["limit"]
        return fake_db[start:end]
        
    mock_query.offset.side_effect = set_offset
    mock_offset.limit.side_effect = set_limit
    mock_limit.all.side_effect = mock_all
    
    # The scorecard endpoint also uses .filter().first()
    mock_filter = MagicMock()
    def mock_first():
        return fake_db[0] if fake_db else None
    mock_filter.first.side_effect = mock_first
    mock_query.filter.return_value = mock_filter
    
    session.query.return_value = mock_query
    return session

app.dependency_overrides[get_database_session] = get_stateful_mock_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_fake_db():
    """Ensure the fake database is empty before every test runs."""
    fake_db.clear()
    yield

def test_empty_suppliers_list():
    """Test the empty case (no suppliers yet)."""
    response = client.get("/api/v1/suppliers")
    assert response.status_code == 200, f"Failed with: {response.text}"
    data = response.json()
    assert data["total"] == 0
    assert len(data["items"]) == 0

def test_add_and_list_supplier():
    """
    Test that adds a supplier, then calls the new GET endpoint, 
    and asserts the supplier appears in the response.
    """
    # 1. Add a supplier
    payload = {
        "name": "Acme Corp",
        "contact_email": "hello@acme.com",
        "industry_vertical": "PHARMACEUTICALS"
    }
    post_res = client.post("/api/v1/suppliers", json=payload)
    assert post_res.status_code == 200, f"Failed to POST: {post_res.text}"
    added_supplier_id = post_res.json()["supplier_id"]
    
    # 2. Get the list of suppliers
    get_res = client.get("/api/v1/suppliers")
    assert get_res.status_code == 200, f"Failed to GET: {get_res.text}"
    data = get_res.json()
    
    # 3. Assert our newly created supplier is in the list
    assert data["total"] == 1
    assert len(data["items"]) == 1
    
    item = data["items"][0]
    assert item["name"] == "Acme Corp"
    assert item["supplier_id"] == added_supplier_id
    assert item["industry_vertical"] == "PHARMACEUTICALS"

def test_invalid_pagination_params():
    """Test for invalid pagination params."""
    # Negative limit
    res1 = client.get("/api/v1/suppliers?limit=-10")
    assert res1.status_code == 400
    assert "Limit" in res1.json()["detail"]
    
    # Negative offset
    res2 = client.get("/api/v1/suppliers?offset=-5")
    assert res2.status_code == 400
    assert "Offset" in res2.json()["detail"]
