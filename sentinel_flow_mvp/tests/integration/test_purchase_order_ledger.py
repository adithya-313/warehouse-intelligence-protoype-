import pytest
from datetime import datetime
from app.infrastructure.models import PurchaseOrderModel, Tenant, SupplierModel
from sqlalchemy import text
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.purchase_order_router import router as purchase_order_router
from app.infrastructure.database import get_database_session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.pool import StaticPool
from app.infrastructure.models import Base

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
def ledger_client(sqlite_db_session):
    app = FastAPI()
    app.include_router(purchase_order_router, prefix="/api/v1")
    app.dependency_overrides[get_database_session] = lambda: sqlite_db_session
    with TestClient(app) as c:
        yield c

class TestPurchaseOrderLedger:
    def test_ledger_shows_vendor_name_and_handles_missing_supplier(self, ledger_client, sqlite_db_session):
        # 1. Setup tenant
        tenant = Tenant(tenant_id="TENANT-LEDGER-1", name="Ledger Pharmacy")
        sqlite_db_session.add(tenant)

        # 2. Setup Medication
        sqlite_db_session.execute(text(
            "INSERT INTO medications (sku_id, apis, therapeutic_classes, cdsco_schedule, is_approved_by_curator) "
            "VALUES ('MED-L-1', '[\"Drug\"]', '[\"Class\"]', 'OTC', 1)"
        ))

        # 3. Setup a known supplier
        known_supplier = SupplierModel(
            supplier_id="SUPP-KNOWN",
            system_origin="TEST",
            industry_vertical="PHARMA",
            industry_specific_metadata={"name": "Known Vendor Inc."}
        )
        sqlite_db_session.add(known_supplier)

        # 4. Setup POs (one with known supplier, one with missing supplier)
        po1 = PurchaseOrderModel(
            po_id="PO-L-1",
            tenant_id="TENANT-LEDGER-1",
            supplier_id="SUPP-KNOWN",
            sku_id="MED-L-1",
            ordered_qty=10,
            cost_price=5.0,
            expected_mrp=10.0,
            order_date=datetime.now().date(),
            expected_delivery_date=datetime.now().date(),
            status="PENDING"
        )
        po2 = PurchaseOrderModel(
            po_id="PO-L-2",
            tenant_id="TENANT-LEDGER-1",
            supplier_id="SUPP-MISSING",
            sku_id="MED-L-1",
            ordered_qty=5,
            cost_price=5.0,
            expected_mrp=10.0,
            order_date=datetime.now().date(),
            expected_delivery_date=datetime.now().date(),
            status="PENDING"
        )
        sqlite_db_session.add_all([po1, po2])
        sqlite_db_session.commit()

        # 5. Call ledger endpoint
        res = ledger_client.get(
            "/api/v1/purchase-orders",
            headers={"x-tenant-id": "TENANT-LEDGER-1"}
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 2

        # Check supplier names
        po1_data = next(po for po in data if po["po_id"] == "PO-L-1")
        po2_data = next(po for po in data if po["po_id"] == "PO-L-2")

        assert po1_data["supplier_name"] == "Known Vendor Inc."
        assert po2_data["supplier_name"] == "Unknown Supplier"
