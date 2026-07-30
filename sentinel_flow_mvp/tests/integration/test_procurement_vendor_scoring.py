import pytest
import uuid
from datetime import datetime, date
from fastapi.testclient import TestClient

from app.main import app
from fastapi import FastAPI
from app.api.purchase_order_router import router as purchase_order_router
from app.api.v1.procurement_router import router as procurement_router
from app.infrastructure.database import get_database_session
from app.api.dependencies import get_current_tenant
from app.infrastructure.models import PurchaseOrderModel, Tenant, MedicationModel, ExogenousCovariateModel, Base
from app.health_risk.infrastructure.db_models import HealthRiskScoreModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from datetime import datetime

# Fix for SQLite not supporting PostgreSQL JSONB and ARRAY
@compiles(JSONB, 'sqlite')
def compile_jsonb_sqlite(type_, compiler, **kw):
    return 'JSON'

@compiles(ARRAY, 'sqlite')
def compile_array_sqlite(type_, compiler, **kw):
    return 'JSON'

from sqlalchemy.pool import StaticPool

@pytest.fixture
def sqlite_db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()

@pytest.fixture
def vendor_scoring_client(sqlite_db_session):
    app = FastAPI()
    app.include_router(purchase_order_router, prefix="/api/v1")
    app.include_router(procurement_router, prefix="/api/v1")
    app.dependency_overrides[get_database_session] = lambda: sqlite_db_session
    app.dependency_overrides[get_current_tenant] = lambda: "TENANT-VS-1"
    with TestClient(app) as c:
        yield c

class TestProcurementVendorScoring:
    def test_vendor_scoring_picks_supplier_with_most_fulfilled_orders(self, vendor_scoring_client, sqlite_db_session, monkeypatch):
        from app.core.config import get_application_settings
        settings = get_application_settings()
        monkeypatch.setattr(settings, "HEALTH_RISK_ENABLED", True)
        
        # 1. Setup tenant context
        tenant = Tenant(
            tenant_id="TENANT-VS-1",
            name="Vendor Scoring Pharmacy",
            pincode="110001",
            health_risk_enabled=True
        )
        sqlite_db_session.add(tenant)
        
        from sqlalchemy import text
        # We need a medication to trigger the wave
        sqlite_db_session.execute(text(
            "INSERT INTO medications (sku_id, apis, therapeutic_classes, cdsco_schedule, is_approved_by_curator) "
            "VALUES ('MED-PARA-100', '[\"Paracetamol\"]', '[\"Antipyretic\"]', 'OTC', 1)"
        ))
        
        # We need a high health risk score to trigger the disease wave alert path
        risk_score = HealthRiskScoreModel(
            pincode="110001",
            disease_category="fever",
            score=85.0,  # Above 70.0 threshold
            confidence="real_data",
            computed_at=datetime.now()
        )
        sqlite_db_session.add(risk_score)
        sqlite_db_session.commit()

        # 2. Setup Suppliers via direct POs
        # Supplier A gets 1 order
        po_ids = []
        res_a = vendor_scoring_client.post(
            "/api/v1/purchase-orders",
            json={
                "supplier_id": "SUPP-A",
                "expected_delivery_date": datetime.now().date().isoformat(),
                "items": [{"sku_id": "MED-PARA-100", "ordered_qty": 50, "cost_price": 5.0, "expected_mrp": 10.0}]
            },
            headers={"x-tenant-id": "TENANT-VS-1"}
        )
        assert res_a.status_code == 200
        po_ids.append(res_a.json()["po_id"])

        # Supplier B gets 3 orders
        for _ in range(3):
            res_b = vendor_scoring_client.post(
                "/api/v1/purchase-orders",
                json={
                    "supplier_id": "SUPP-B",
                    "expected_delivery_date": datetime.now().date().isoformat(),
                    "items": [{"sku_id": "MED-PARA-100", "ordered_qty": 100, "cost_price": 4.5, "expected_mrp": 10.0}]
                },
                headers={"x-tenant-id": "TENANT-VS-1"}
            )
            assert res_b.status_code == 200
            po_ids.append(res_b.json()["po_id"])

        # Supplier C gets 5 PENDING orders (we won't receive them)
        for _ in range(5):
            res_c = vendor_scoring_client.post(
                "/api/v1/purchase-orders",
                json={
                    "supplier_id": "SUPP-C",
                    "expected_delivery_date": datetime.now().date().isoformat(),
                    "items": [{"sku_id": "MED-PARA-100", "ordered_qty": 20, "cost_price": 4.0, "expected_mrp": 10.0}]
                },
                headers={"x-tenant-id": "TENANT-VS-1"}
            )
            assert res_c.status_code == 200

        # 3. Receive Supplier A and B orders to make them FULFILLED
        for po_id in po_ids:
            res_rec = vendor_scoring_client.post(
                "/api/v1/purchase-orders/receive",
                json={
                    "po_id": po_id,
                    "actual_delivery_date": datetime.now().date().isoformat(),
                    "items": [{"sku_id": "MED-PARA-100", "delivered_qty": 10}]
                },
                headers={"x-tenant-id": "TENANT-VS-1"}
            )
            assert res_rec.status_code == 200

        # 4. Trigger Disease Wave Alerts, which evaluates best supplier
        res_alerts = vendor_scoring_client.get(
            "/api/v1/procurement/disease-wave-alerts",
            headers={"x-tenant-id": "TENANT-VS-1"}
        )
        
        assert res_alerts.status_code == 200
        alerts = res_alerts.json()
        
        assert len(alerts) > 0
        
        # The best supplier selected should be SUPP-B because it has 3 FULFILLED orders
        # SUPP-A has 1, SUPP-C has 0 FULFILLED
        # Note: Before our bug fix, the code filtered by "COMPLETED", which matched 0 orders.
        # So it would have fallen back to the hardcoded default "SUPP-001".
        # Now it should pick "SUPP-B".
        assert alerts[0]["recommended_supplier_id"] == "SUPP-B", f"Expected SUPP-B, but got {alerts[0]['recommended_supplier_id']}"
