"""
Tests for audit logging in POS checkout and supplier onboarding endpoints.

Verifies:
1. Checkout with NEW phone → 4 audit calls (patient CREATE, receipt CREATE,
   medication_batch UPDATE, sale_receipt UPDATE) with correct old/new values
2. Checkout with EXISTING phone → 3 audit calls (no patient CREATE)
3. Add-vendor → 1 audit call (supplier CREATE) with correct new_value

Uses FastAPI TestClient + SQLite in-memory DB. Mocks log_audit_event to
avoid BigInteger autoincrement issues in SQLite while verifying call args.
"""

import uuid
from datetime import date
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

from app.infrastructure.models import (
    Base, Tenant, Patient, MedicationBatchModel,
)
from app.api.pos_router import router as pos_router
from app.api.supplier_router import router as supplier_router
from app.infrastructure.database import get_database_session
from app.api.dependencies import get_current_tenant


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "JSON"

@compiles(ARRAY, "sqlite")
def compile_array_sqlite(type_, compiler, **kw):
    return "JSON"


@pytest.fixture
def sqlite_db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def checkout_client(sqlite_db_session):
    app = FastAPI()
    app.include_router(pos_router, prefix="/api/v1/pos")
    app.dependency_overrides[get_database_session] = lambda: sqlite_db_session
    app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"
    with TestClient(app) as c:
        yield c


@patch("app.api.pos_router.log_audit_event")
@patch("app.api.pos_router.mark_checkout_completed")
@patch("app.api.pos_router.is_above_checkout_rate_limit", return_value=False)
@patch("app.api.pos_router.is_duplicate_checkout_request", return_value=False)
def test_checkout_new_patient_writes_4_audit_entries(
    mock_is_dup,
    mock_is_rate,
    mock_mark,
    mock_log_audit,
    checkout_client,
    sqlite_db_session,
):
    """
    Checkout with a phone number that does NOT exist in patients table
    should produce exactly 4 audit calls:
      1. patient CREATE (old=None, new has name+phone)
      2. sale_receipt CREATE (old=None, new has total=0, payment_method, patient_id)
      3. medication_batch UPDATE (old has real available_quantity, new has decremented)
      4. sale_receipt UPDATE (old total=0, new total=calculated)
    """
    # ARRANGE: seed a tenant and a batch with 50 units
    sqlite_db_session.add(Tenant(tenant_id="test-tenant-001", name="Test Pharmacy"))
    batch = MedicationBatchModel(
        batch_id="BATCH-AUDIT-001",
        tenant_id="test-tenant-001",
        sku_id="SKU-PARA-500",
        cost_price=8.0,
        max_retail_price=12.0,
        available_quantity=50,
        expiry_date=date(2027, 12, 31),
    )
    sqlite_db_session.add(batch)
    sqlite_db_session.commit()

    payload = {
        "items": [
            {
                "batch_id": "BATCH-AUDIT-001",
                "sku_id": "SKU-PARA-500",
                "name": "Paracetamol 500mg",
                "quantity": 2,
                "price": 10.0,
            }
        ],
        "payment_method": "CASH",
        "idempotency_key": str(uuid.uuid4()),
        "customer_phone": "9876543210",
        "customer_name": "New Patient",
    }

    # ACT
    response = checkout_client.post("/api/v1/pos/checkout", json=payload)
    assert response.status_code == 200

    # ASSERT: exactly 4 audit calls
    assert mock_log_audit.call_count == 4

    # --- Call 1: Patient CREATE ---
    c1 = mock_log_audit.call_args_list[0][1]
    assert c1["entity_type"] == "patient"
    assert c1["action_type"] == "CREATE"
    assert c1["old_value"] is None
    assert c1["new_value"]["phone_number"] == "9876543210"
    assert c1["new_value"]["name"] == "New Patient"
    assert c1["tenant_id"] == "test-tenant-001"

    # --- Call 2: Sale Receipt CREATE ---
    c2 = mock_log_audit.call_args_list[1][1]
    assert c2["entity_type"] == "sale_receipt"
    assert c2["action_type"] == "CREATE"
    assert c2["old_value"] is None
    assert c2["new_value"]["total_amount_inr"] == 0
    assert c2["new_value"]["payment_method"] == "CASH"
    assert c2["new_value"]["patient_id"] is not None
    assert c2["tenant_id"] == "test-tenant-001"

    # --- Call 3: Medication Batch UPDATE (real before/after) ---
    c3 = mock_log_audit.call_args_list[2][1]
    assert c3["entity_type"] == "medication_batch"
    assert c3["action_type"] == "UPDATE"
    assert c3["entity_id"] == "BATCH-AUDIT-001"
    assert c3["old_value"]["available_quantity"] == 50
    assert c3["new_value"]["available_quantity"] == 48
    assert c3["tenant_id"] == "test-tenant-001"

    # --- Call 4: Sale Receipt UPDATE (total 0 → 20) ---
    c4 = mock_log_audit.call_args_list[3][1]
    assert c4["entity_type"] == "sale_receipt"
    assert c4["action_type"] == "UPDATE"
    assert c4["old_value"]["total_amount_inr"] == 0
    assert c4["new_value"]["total_amount_inr"] == 20.0
    assert c4["tenant_id"] == "test-tenant-001"

    # Also verify the batch quantity was actually deducted in the DB
    from app.infrastructure.models import MedicationBatchModel as MB
    updated_batch = sqlite_db_session.query(MB).filter(MB.batch_id == "BATCH-AUDIT-001").first()
    assert updated_batch.available_quantity == 48


@patch("app.api.pos_router.log_audit_event")
@patch("app.api.pos_router.mark_checkout_completed")
@patch("app.api.pos_router.is_above_checkout_rate_limit", return_value=False)
@patch("app.api.pos_router.is_duplicate_checkout_request", return_value=False)
def test_checkout_existing_patient_writes_3_audit_entries(
    mock_is_dup,
    mock_is_rate,
    mock_mark,
    mock_log_audit,
    checkout_client,
    sqlite_db_session,
):
    """
    Checkout with an EXISTING phone number should produce exactly 3 audit
    calls (no patient CREATE).
    """
    # ARRANGE: seed tenant, existing patient, and a batch
    sqlite_db_session.add(Tenant(tenant_id="test-tenant-001", name="Test Pharmacy"))
    patient = Patient(
        patient_id="PATIENT-EXISTING-001",
        tenant_id="test-tenant-001",
        name="Existing Patient",
        phone_number="9876543210",
    )
    sqlite_db_session.add(patient)
    batch = MedicationBatchModel(
        batch_id="BATCH-AUDIT-002",
        tenant_id="test-tenant-001",
        sku_id="SKU-AMOX-250",
        cost_price=20.0,
        max_retail_price=30.0,
        available_quantity=100,
        expiry_date=date(2027, 6, 30),
    )
    sqlite_db_session.add(batch)
    sqlite_db_session.commit()

    payload = {
        "items": [
            {
                "batch_id": "BATCH-AUDIT-002",
                "sku_id": "SKU-AMOX-250",
                "name": "Amoxicillin 250mg",
                "quantity": 3,
                "price": 25.0,
            }
        ],
        "payment_method": "UPI",
        "idempotency_key": str(uuid.uuid4()),
        "customer_phone": "9876543210",
        "customer_name": "Existing Patient",
    }

    # ACT
    response = checkout_client.post("/api/v1/pos/checkout", json=payload)
    assert response.status_code == 200

    # ASSERT: exactly 3 audit calls (no patient CREATE)
    assert mock_log_audit.call_count == 3

    entity_types = [call[1]["entity_type"] for call in mock_log_audit.call_args_list]
    action_types = [call[1]["action_type"] for call in mock_log_audit.call_args_list]

    # No patient row
    assert "patient" not in entity_types

    # Verify the 3 entries
    assert entity_types[0] == "sale_receipt" and action_types[0] == "CREATE"
    assert entity_types[1] == "medication_batch" and action_types[1] == "UPDATE"
    assert mock_log_audit.call_args_list[1][1]["old_value"]["available_quantity"] == 100
    assert mock_log_audit.call_args_list[1][1]["new_value"]["available_quantity"] == 97
    assert entity_types[2] == "sale_receipt" and action_types[2] == "UPDATE"
    assert mock_log_audit.call_args_list[2][1]["new_value"]["total_amount_inr"] == 75.0


@pytest.fixture
def vendor_client(sqlite_db_session):
    app = FastAPI()
    app.include_router(supplier_router, prefix="/api/v1/suppliers")
    app.dependency_overrides[get_database_session] = lambda: sqlite_db_session
    with TestClient(app) as c:
        yield c


@patch("app.api.supplier_router.log_audit_event")
def test_add_vendor_writes_1_audit_entry(mock_log_audit, vendor_client, sqlite_db_session):
    """
    Onboarding a new supplier should produce exactly 1 audit call:
      supplier CREATE with old=None, new has name/contact/industry/system_origin.
    """
    payload = {
        "name": "Test Pharma Co",
        "contact_email": "test@pharma.com",
        "industry_vertical": "PHARMACEUTICALS",
    }

    response = vendor_client.post("/api/v1/suppliers", json=payload)
    assert response.status_code == 200

    # Exactly 1 audit call
    assert mock_log_audit.call_count == 1

    c1 = mock_log_audit.call_args_list[0][1]
    assert c1["entity_type"] == "supplier"
    assert c1["action_type"] == "CREATE"
    assert c1["old_value"] is None
    assert c1["new_value"]["name"] == "Test Pharma Co"
    assert c1["new_value"]["contact_email"] == "test@pharma.com"
    assert c1["new_value"]["industry_vertical"] == "PHARMACEUTICALS"
    assert c1["new_value"]["system_origin"] == "USER_PORTAL"
    assert c1["tenant_id"] == "system_admin"

    # Supplier was actually created in the DB
    from app.infrastructure.models import SupplierModel
    supplier = sqlite_db_session.query(SupplierModel).first()
    assert supplier is not None
    assert supplier.industry_vertical == "PHARMACEUTICALS"
