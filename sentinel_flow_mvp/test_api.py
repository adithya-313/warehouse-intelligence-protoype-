import sys
import json
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

def run():
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
    db.add(tenant)
    
    # Add a late FULFILLED purchase order
    po = PurchaseOrderModel(
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
        actual_delivery_date=date(2026, 8, 10), # 7 days late
        status="FULFILLED"
    )
    db.add(po)
    
    supplier = SupplierModel(
        supplier_id="SUP-1",
        system_origin="MANUAL",
        industry_vertical="PHARMA",
        industry_specific_metadata={"name": "Slow Supplier"}
    )
    db.add(supplier)
    # Add an ON-TIME FULFILLED order
    po2 = PurchaseOrderModel(
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
        actual_delivery_date=date(2026, 8, 5), # On time
        status="FULFILLED"
    )
    db.add(po2)
    
    # Add a PENDING order
    po3 = PurchaseOrderModel(
        po_id="PO-PENDING-125",
        tenant_id="T1",
        supplier_id="SUP-1",
        sku_id="SKU-3",
        ordered_qty=20,
        delivered_qty=0,
        cost_price=5.0,
        expected_mrp=10.0,
        order_date=date(2026, 8, 3),
        expected_delivery_date=date(2026, 8, 20),
        actual_delivery_date=None,
        status="PENDING"
    )
    db.add(po3)
    
    # Add another supplier with 0 orders
    supplier2 = SupplierModel(
        supplier_id="SUP-EMPTY",
        system_origin="MANUAL",
        industry_vertical="PHARMA",
        industry_specific_metadata={"name": "Empty Supplier"}
    )
    db.add(supplier2)
    
    db.commit()
    
    def _override():
        db_yield = SessionLocal()
        yield db_yield
        db_yield.close()
        
    app.dependency_overrides[get_database_session] = _override
    client = TestClient(app)
    headers = {"X-Tenant-ID": "T1"}
    
    res_orders = client.get("/api/v1/suppliers/SUP-1/orders", headers=headers)
    print("--- API Response (Mixed Orders) ---")
    print(json.dumps(res_orders.json(), indent=2))
    
    res_empty = client.get("/api/v1/suppliers/SUP-EMPTY/orders", headers=headers)
    print("\n--- API Response (Empty History) ---")
    print(json.dumps(res_empty.json(), indent=2))

if __name__ == "__main__":
    run()
