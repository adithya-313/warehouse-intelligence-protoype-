import pytest
from datetime import date
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

# We set up a test db with 3 POs on the exact same order_date
@pytest.fixture
def sqlite_db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from app.infrastructure.models import Base
    Base.metadata.create_all(bind=engine)
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    # 1. Setup tenant
    tenant = Tenant(tenant_id="T1", name="Test Tenant")
    db.add(tenant)
    
    # 2. Setup Supplier
    supplier = SupplierModel(
        supplier_id="SUPP-1",
        system_origin="TEST",
        industry_vertical="PHARMA",
        industry_specific_metadata={"name": "Known Vendor Inc."}
    )
    db.add(supplier)
    
    # 3. Setup exactly same-day POs
    today = date(2026, 8, 3)
    
    # Notice we insert them in an arbitrary order, but po_id will be sorted deterministically
    po1 = PurchaseOrderModel(
        po_id="PO-B", 
        tenant_id="T1",
        supplier_id="SUPP-1",
        sku_id="SKU-1",
        ordered_qty=10,
        cost_price=10.0,
        expected_mrp=15.0,
        order_date=today,
        expected_delivery_date=today,
        status="PENDING"
    )
    po2 = PurchaseOrderModel(
        po_id="PO-C", 
        tenant_id="T1",
        supplier_id="SUPP-1",
        sku_id="SKU-1",
        ordered_qty=10,
        cost_price=10.0,
        expected_mrp=15.0,
        order_date=today,
        expected_delivery_date=today,
        status="PENDING"
    )
    po3 = PurchaseOrderModel(
        po_id="PO-A", 
        tenant_id="T1",
        supplier_id="SUPP-1",
        sku_id="SKU-1",
        ordered_qty=10,
        cost_price=10.0,
        expected_mrp=15.0,
        order_date=today,
        expected_delivery_date=today,
        status="PENDING"
    )
    
    db.add_all([po1, po2, po3])
    db.commit()
    
    yield db
    db.close()


@pytest.fixture
def override_get_db(sqlite_db_session):
    def _override():
        yield sqlite_db_session
    app.dependency_overrides[get_database_session] = _override
    yield
    app.dependency_overrides.pop(get_database_session, None)


def test_purchase_order_list_is_stable_for_same_day_orders(override_get_db):
    """
    Test proves that multiple requests return the EXACT same order when order_dates tie.
    """
    client = TestClient(app)
    
    # Call 1
    res1 = client.get("/api/v1/purchase-orders", headers={"x-tenant-id": "T1"})
    assert res1.status_code == 200
    data1 = res1.json()
    
    assert len(data1) == 3
    order_sequence_1 = [po["po_id"] for po in data1]
    
    # Call 5 times and assert the sequence is identical
    for i in range(5):
        res = client.get("/api/v1/purchase-orders", headers={"x-tenant-id": "T1"})
        assert res.status_code == 200
        current_sequence = [po["po_id"] for po in res.json()]
        
        # This proves the fix actually eliminates randomness
        assert current_sequence == order_sequence_1, (
            f"Run {i+1} returned a different order! Expected {order_sequence_1}, got {current_sequence}"
        )
        
        # Verify it is sorted by po_id.desc() since order_date is tied
        assert current_sequence == ["PO-C", "PO-B", "PO-A"]

