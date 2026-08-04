import pytest
from datetime import date
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

from app.infrastructure.models import Base, SupplierModel, PurchaseOrderModel, Tenant
from app.api.supplier_router import router as supplier_router
from app.infrastructure.database import get_database_session

@compiles(JSONB, 'sqlite')
def compile_jsonb_sqlite(type_, compiler, **kw):
    return 'JSON'

@compiles(ARRAY, 'sqlite')
def compile_array_sqlite(type_, compiler, **kw):
    return 'JSON'

@pytest.fixture
def sqlite_db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()

@pytest.fixture
def client(sqlite_db_session):
    app = FastAPI()
    app.include_router(supplier_router, prefix="/api/v1/suppliers")
    app.dependency_overrides[get_database_session] = lambda: sqlite_db_session
    with TestClient(app) as c:
        yield c

def test_supplier_history_endpoint(client: TestClient, sqlite_db_session):
    # Setup data
    tenant = Tenant(tenant_id="T1", name="Test Tenant")
    sqlite_db_session.add(tenant)
    
    supplier1 = SupplierModel(
        supplier_id="SUP-1",
        system_origin="MANUAL",
        industry_vertical="PHARMA",
        industry_specific_metadata={"name": "Fast Supplier"}
    )
    sqlite_db_session.add(supplier1)
    
    supplier2 = SupplierModel(
        supplier_id="SUP-EMPTY",
        system_origin="MANUAL",
        industry_vertical="PHARMA",
        industry_specific_metadata={"name": "Empty Supplier"}
    )
    sqlite_db_session.add(supplier2)
    
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
    sqlite_db_session.add(po_late)
    
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
    sqlite_db_session.add(po_ontime)
    
    sqlite_db_session.commit()

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
