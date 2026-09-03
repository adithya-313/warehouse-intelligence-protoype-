"""
Why this test exists:
This test verifies that the /api/v1/pos/history endpoint enforces multi-tenant isolation.
Without the .filter(SaleReceiptModel.tenant_id == tenant_id) clause in pos_router.py,
a request from Tenant A could leak Tenant B's sales receipts. This is a critical security
test that prevents cross-tenant data leakage.
"""

import pytest
from datetime import datetime, timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

from app.infrastructure.models import Base, SaleReceiptModel, SaleLineItemModel, Tenant
from app.api.pos_router import router as pos_router
from app.infrastructure.database import get_database_session

# Compile PostgreSQL-specific types to work in SQLite
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
    app.include_router(pos_router, prefix="/api/v1/pos")
    app.dependency_overrides[get_database_session] = lambda: sqlite_db_session
    with TestClient(app) as c:
        yield c

def test_pos_history_tenant_isolation(client: TestClient, sqlite_db_session):
    """
    Test that /history only returns receipts belonging to the requesting tenant.
    
    This is a critical security test: without the tenant_id filter, a request
    from Tenant A could leak Tenant B's sales receipts.
    """
    # Setup: Create two tenants
    tenant_a = Tenant(tenant_id="TENANT_A", name="Pharmacy A")
    tenant_b = Tenant(tenant_id="TENANT_B", name="Pharmacy B")
    sqlite_db_session.add(tenant_a)
    sqlite_db_session.add(tenant_b)

    # Create receipts for Tenant A
    receipt_a1 = SaleReceiptModel(
        id="REC-A-001",
        tenant_id="TENANT_A",
        total_amount_inr=150.00,
        payment_method="CASH",
        timestamp=datetime.now() - timedelta(hours=1)
    )
    receipt_a2 = SaleReceiptModel(
        id="REC-A-002",
        tenant_id="TENANT_A",
        total_amount_inr=250.00,
        payment_method="CARD",
        timestamp=datetime.now()
    )
    sqlite_db_session.add(receipt_a1)
    sqlite_db_session.add(receipt_a2)

    # Create a receipt for Tenant B
    receipt_b1 = SaleReceiptModel(
        id="REC-B-001",
        tenant_id="TENANT_B",
        total_amount_inr=300.00,
        payment_method="CASH",
        timestamp=datetime.now()
    )
    sqlite_db_session.add(receipt_b1)

    # Create line items for the receipts
    line_a1 = SaleLineItemModel(
        tenant_id="TENANT_A",
        receipt_id="REC-A-001",
        batch_id="BATCH-001",
        name="Paracetamol 500mg",
        quantity_sold=2,
        price_per_unit=50.00
    )
    line_a2 = SaleLineItemModel(
        tenant_id="TENANT_A",
        receipt_id="REC-A-002",
        batch_id="BATCH-002",
        name="Amoxicillin 250mg",
        quantity_sold=1,
        price_per_unit=150.00
    )
    line_b1 = SaleLineItemModel(
        tenant_id="TENANT_B",
        receipt_id="REC-B-001",
        batch_id="BATCH-003",
        name="Ibuprofen 400mg",
        quantity_sold=3,
        price_per_unit=100.00
    )
    sqlite_db_session.add_all([line_a1, line_a2, line_b1])
    sqlite_db_session.commit()

    # Test: Request history as Tenant A
    response_a = client.get("/api/v1/pos/history", headers={"X-Tenant-ID": "TENANT_A"})
    assert response_a.status_code == 200
    data_a = response_a.json()

    # Tenant A should only see its own receipts (2 receipts)
    assert len(data_a) == 2
    receipt_ids_a = [r["id"] for r in data_a]
    assert "REC-A-001" in receipt_ids_a
    assert "REC-A-002" in receipt_ids_a
    assert "REC-B-001" not in receipt_ids_a  # Tenant B's receipt must NOT appear

    # Test: Request history as Tenant B
    response_b = client.get("/api/v1/pos/history", headers={"X-Tenant-ID": "TENANT_B"})
    assert response_b.status_code == 200
    data_b = response_b.json()

    # Tenant B should only see its own receipt (1 receipt)
    assert len(data_b) == 1
    assert data_b[0]["id"] == "REC-B-001"
    assert data_b[0]["total_amount_inr"] == 300.00
