import pytest
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.infrastructure.database import get_database_session
from app.infrastructure.models import SupplierModel, PurchaseOrderModel

@pytest.fixture
def client(mock_db_session: Session):
    def _override():
        yield mock_db_session
    app.dependency_overrides[get_database_session] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

def test_supplier_history_endpoint(client: TestClient, mock_db_session: Session):
    # Setup data
    supplier1 = SupplierModel(
        supplier_id="SUP-1",
        system_origin="MANUAL",
        industry_vertical="PHARMA",
        industry_specific_metadata={"name": "Fast Supplier"}
    )
    mock_db_session.add(supplier1)
    
    supplier2 = SupplierModel(
        supplier_id="SUP-EMPTY",
        system_origin="MANUAL",
        industry_vertical="PHARMA",
        industry_specific_metadata={"name": "Empty Supplier"}
    )
    mock_db_session.add(supplier2)
    
    po_late = PurchaseOrderModel(
        po_id="PO-LATE-123",
        tenant_id="T1",
        supplier_id="SUP-1",
        sku_id="SKU-1",
        ordered_qty=10,
        delivered_qty=10,
        cost_price=10.0,
        expected_mrp=15.0,
        order_date=date(2026, 8, 1),
        expected_delivery_date=date(2026, 8, 3),
        actual_delivery_date=date(2026, 8, 10),
        status="FULFILLED"
    )
    mock_db_session.add(po_late)
    
    po_ontime = PurchaseOrderModel(
        po_id="PO-ONTIME-124",
        tenant_id="T1",
        supplier_id="SUP-1",
        sku_id="SKU-2",
        ordered_qty=5,
        delivered_qty=5,
        cost_price=20.0,
        expected_mrp=25.0,
        order_date=date(2026, 8, 2),
        expected_delivery_date=date(2026, 8, 5),
        actual_delivery_date=date(2026, 8, 5),
        status="FULFILLED"
    )
    mock_db_session.add(po_ontime)
    
    mock_db_session.commit()

    headers = {"X-Tenant-ID": "T1"}
    
    # Test Mixed Orders
    res = client.get("/api/v1/suppliers/SUP-1/orders", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    
    # Assert sorted by order_date desc
    assert data[0]["po_id"] == "PO-ONTIME-124"
    assert data[1]["po_id"] == "PO-LATE-123"
    
    # Test Empty Orders
    res_empty = client.get("/api/v1/suppliers/SUP-EMPTY/orders", headers=headers)
    assert res_empty.status_code == 200
    assert res_empty.json() == []
