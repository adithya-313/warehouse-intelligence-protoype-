import pytest
from datetime import date, timezone, datetime
from fastapi.testclient import TestClient
from app.main import app
from app.infrastructure.database import get_database_session
from app.infrastructure.models import PurchaseOrderModel, SupplierModel, Tenant
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

@compiles(JSONB, 'sqlite')
def compile_jsonb_sqlite(type_, compiler, **kw):
    return 'JSON'

@compiles(ARRAY, 'sqlite')
def compile_array_sqlite(type_, compiler, **kw):
    return 'JSON'

@pytest.fixture
def override_db_for_receive():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from app.infrastructure.models import Base
    Base.metadata.create_all(bind=engine)
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    tenant = Tenant(tenant_id="T1", name="Test Tenant")
    supplier = SupplierModel(
        supplier_id="SUPP-1",
        system_origin="TEST",
        industry_vertical="PHARMA",
        industry_specific_metadata={"name": "Known Vendor Inc."}
    )
    db.add(tenant)
    db.add(supplier)
    
    # 1. PO for Single full delivery
    po_full = PurchaseOrderModel(
        po_id="PO-FULL", tenant_id="T1", supplier_id="SUPP-1", sku_id="SKU-FULL",
        ordered_qty=10, delivered_qty=0, cost_price=10.0, expected_mrp=15.0,
        order_date=date(2026, 8, 3), expected_delivery_date=date(2026, 8, 4), status="SUBMITTED"
    )
    
    # 2. PO for Partial delivery / Two shipments
    po_multi = PurchaseOrderModel(
        po_id="PO-MULTI", tenant_id="T1", supplier_id="SUPP-1", sku_id="SKU-MULTI",
        ordered_qty=20, delivered_qty=0, cost_price=10.0, expected_mrp=15.0,
        order_date=date(2026, 8, 3), expected_delivery_date=date(2026, 8, 4), status="SUBMITTED"
    )
    
    # 3. PO for Over-delivery
    po_over = PurchaseOrderModel(
        po_id="PO-OVER", tenant_id="T1", supplier_id="SUPP-1", sku_id="SKU-OVER",
        ordered_qty=5, delivered_qty=0, cost_price=10.0, expected_mrp=15.0,
        order_date=date(2026, 8, 3), expected_delivery_date=date(2026, 8, 4), status="SUBMITTED"
    )
    
    db.add_all([po_full, po_multi, po_over])
    db.commit()
    
    def _override():
        db_yield = SessionLocal()
        yield db_yield
        db_yield.close()
        
    app.dependency_overrides[get_database_session] = _override
    yield db
    app.dependency_overrides.pop(get_database_session, None)


def test_single_full_delivery(override_db_for_receive):
    client = TestClient(app)
    
    payload = {
        "po_id": "PO-FULL",
        "actual_delivery_date": str(date(2026, 8, 4)),
        "items": [
            {"sku_id": "SKU-FULL", "delivered_qty": 10}
        ]
    }
    
    res = client.post("/api/v1/purchase-orders/receive", json=payload)
    assert res.status_code == 200
    assert res.json()["status"] == "FULFILLED"
    
    # Verify in DB
    po = override_db_for_receive.query(PurchaseOrderModel).filter(PurchaseOrderModel.po_id == "PO-FULL").first()
    assert po.status == "FULFILLED"
    assert po.delivered_qty == 10
    print(f"PO-FULL: Delivered {po.delivered_qty}/{po.ordered_qty}, Status: {po.status}")


def test_two_partial_deliveries(override_db_for_receive):
    client = TestClient(app)
    
    # First delivery: 5 out of 20
    payload1 = {
        "po_id": "PO-MULTI",
        "actual_delivery_date": str(date(2026, 8, 4)),
        "items": [
            {"sku_id": "SKU-MULTI", "delivered_qty": 5}
        ]
    }
    
    res1 = client.post("/api/v1/purchase-orders/receive", json=payload1)
    assert res1.status_code == 200
    assert res1.json()["status"] == "PARTIAL"
    
    # Verify DB after first delivery
    override_db_for_receive.expire_all()
    po = override_db_for_receive.query(PurchaseOrderModel).filter(PurchaseOrderModel.po_id == "PO-MULTI").first()
    assert po.status == "PARTIAL"
    assert po.delivered_qty == 5
    print(f"PO-MULTI (Shipment 1): Delivered {po.delivered_qty}/{po.ordered_qty}, Status: {po.status}")
    
    # Second delivery: remaining 15 out of 20
    payload2 = {
        "po_id": "PO-MULTI",
        "actual_delivery_date": str(date(2026, 8, 5)),
        "items": [
            {"sku_id": "SKU-MULTI", "delivered_qty": 15}
        ]
    }
    
    res2 = client.post("/api/v1/purchase-orders/receive", json=payload2)
    assert res2.status_code == 200
    assert res2.json()["status"] == "FULFILLED"
    
    # Verify DB after second delivery (accumulated correctly)
    override_db_for_receive.expire_all()
    po = override_db_for_receive.query(PurchaseOrderModel).filter(PurchaseOrderModel.po_id == "PO-MULTI").first()
    assert po.status == "FULFILLED"
    assert po.delivered_qty == 20
    print(f"PO-MULTI (Shipment 2): Delivered {po.delivered_qty}/{po.ordered_qty}, Status: {po.status}")


def test_over_delivery(override_db_for_receive):
    client = TestClient(app)
    
    # Try to deliver 10 for an order of 5
    payload = {
        "po_id": "PO-OVER",
        "actual_delivery_date": str(date(2026, 8, 4)),
        "items": [
            {"sku_id": "SKU-OVER", "delivered_qty": 10}
        ]
    }
    
    res = client.post("/api/v1/purchase-orders/receive", json=payload)
    assert res.status_code == 200
    
    # Verify DB capped it at 5 and status is FULFILLED
    override_db_for_receive.expire_all()
    po = override_db_for_receive.query(PurchaseOrderModel).filter(PurchaseOrderModel.po_id == "PO-OVER").first()
    assert po.status == "FULFILLED"
    assert po.delivered_qty == 5
    print(f"PO-OVER: Delivered {po.delivered_qty}/{po.ordered_qty}, Status: {po.status}")


def test_auto_po_idempotency_with_submitted(override_db_for_receive):
    """
    Tests that idempotency logic correctly catches SUBMITTED orders instead of PENDING.
    """
    client = TestClient(app)
    
    # First call: Should create
    payload = {
        "sku_id": "SKU-AUTO-IDO",
        "supplier_id": "SUPP-1",
        "quantity": 10
    }
    
    res1 = client.post("/api/v1/procurement/auto-po", headers={"x-tenant-id": "T1"}, json=payload)
    assert res1.status_code == 200
    assert res1.json()["status"] == "SUBMITTED"
    po_id = res1.json()["po_id"]
    print(f"AUTO-PO First Run: Created {po_id}, Status: {res1.json()['status']}")
    
    # Second call for the same SKU: Should trigger idempotency
    res2 = client.post("/api/v1/procurement/auto-po", headers={"x-tenant-id": "T1"}, json=payload)
    assert res2.status_code == 200
    assert res2.json()["po_id"] == po_id # Should return the same PO ID
    assert "Existing submitted order found" in res2.json()["message"]
    print(f"AUTO-PO Second Run: Message: '{res2.json()['message']}'")
