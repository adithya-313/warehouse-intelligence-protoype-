"""
Why this test exists:
This test verifies that the GET /api/v1/audit-logs endpoint enforces
multi-tenant isolation. Without the .filter(AuditLogModel.tenant_id == tenant_id)
clause in audit_log_router.py, Tenant A could see Tenant B's audit entries,
which reveals what medications were ordered, when, and from which suppliers.
This is the exact bug class we fixed in Phase A (the /history cross-tenant leak).
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

from app.infrastructure.models import Base, AuditLogModel, Tenant
from app.api.v1.audit_log_router import router as audit_log_router
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
def client(sqlite_db_session):
    app = FastAPI()
    app.include_router(audit_log_router, prefix="/api/v1/audit-logs")
    app.dependency_overrides[get_database_session] = lambda: sqlite_db_session
    with TestClient(app) as c:
        yield c


def test_audit_logs_tenant_isolation(client: TestClient, sqlite_db_session):
    """
    Test that /audit-logs only returns entries belonging to the requesting tenant.

    This is a critical security test: without the tenant_id filter, a request
    from Tenant A could leak Tenant B's audit log entries.
    """
    # Setup: Create two tenants
    tenant_a = Tenant(tenant_id="TENANT_A", name="Pharmacy A")
    tenant_b = Tenant(tenant_id="TENANT_B", name="Pharmacy B")
    sqlite_db_session.add(tenant_a)
    sqlite_db_session.add(tenant_b)

    # Create audit entries for Tenant A
    entry_a1 = AuditLogModel(
        id=1,
        tenant_id="TENANT_A",
        entity_type="purchase_order",
        entity_id="PO-A-001",
        action_type="CREATE",
        old_value=None,
        new_value={"status": "PENDING"},
        extra_metadata=None,
        timestamp=datetime.now() - timedelta(hours=2),
    )
    entry_a2 = AuditLogModel(
        id=2,
        tenant_id="TENANT_A",
        entity_type="purchase_order",
        entity_id="PO-A-001",
        action_type="UPDATE",
        old_value={"status": "PENDING"},
        new_value={"status": "RECEIVED"},
        extra_metadata=None,
        timestamp=datetime.now() - timedelta(hours=1),
    )
    sqlite_db_session.add(entry_a1)
    sqlite_db_session.add(entry_a2)

    # Create an audit entry for Tenant B
    entry_b1 = AuditLogModel(
        id=3,
        tenant_id="TENANT_B",
        entity_type="purchase_order",
        entity_id="PO-B-001",
        action_type="CREATE",
        old_value=None,
        new_value={"status": "PENDING"},
        extra_metadata=None,
        timestamp=datetime.now(),
    )
    sqlite_db_session.add(entry_b1)
    sqlite_db_session.commit()

    # Test: Request as Tenant A
    response_a = client.get("/api/v1/audit-logs", headers={"X-Tenant-ID": "TENANT_A"})
    assert response_a.status_code == 200
    data_a = response_a.json()

    # Tenant A should only see its own entries (2 entries)
    assert data_a["total"] == 2
    assert len(data_a["items"]) == 2
    entity_ids_a = [e["entity_id"] for e in data_a["items"]]
    assert "PO-A-001" in entity_ids_a
    assert "PO-B-001" not in entity_ids_a  # Tenant B's entry must NOT appear

    # Test: Request as Tenant B
    response_b = client.get("/api/v1/audit-logs", headers={"X-Tenant-ID": "TENANT_B"})
    assert response_b.status_code == 200
    data_b = response_b.json()

    # Tenant B should only see its own entry (1 entry)
    assert data_b["total"] == 1
    assert len(data_b["items"]) == 1
    assert data_b["items"][0]["entity_id"] == "PO-B-001"


def test_audit_logs_pagination(client: TestClient, sqlite_db_session):
    """Test that limit/offset pagination works correctly."""
    tenant = Tenant(tenant_id="TENANT_PAG", name="Pharmacy Pag")
    sqlite_db_session.add(tenant)

    # Create 5 entries
    for i in range(5):
        entry = AuditLogModel(
            id=100 + i,
            tenant_id="TENANT_PAG",
            entity_type="purchase_order",
            entity_id=f"PO-PAG-{i:03d}",
            action_type="CREATE",
            old_value=None,
            new_value=None,
            extra_metadata=None,
            timestamp=datetime.now() - timedelta(minutes=5 - i),
        )
        sqlite_db_session.add(entry)
    sqlite_db_session.commit()

    # Page 1: limit=2, offset=0
    r1 = client.get("/api/v1/audit-logs?limit=2&offset=0", headers={"X-Tenant-ID": "TENANT_PAG"})
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["total"] == 5
    assert len(d1["items"]) == 2
    assert d1["limit"] == 2
    assert d1["offset"] == 0

    # Page 2: limit=2, offset=2
    r2 = client.get("/api/v1/audit-logs?limit=2&offset=2", headers={"X-Tenant-ID": "TENANT_PAG"})
    assert r2.status_code == 200
    d2 = r2.json()
    assert len(d2["items"]) == 2

    # Page 3: limit=2, offset=4 (only 1 remaining)
    r3 = client.get("/api/v1/audit-logs?limit=2&offset=4", headers={"X-Tenant-ID": "TENANT_PAG"})
    assert r3.status_code == 200
    d3 = r3.json()
    assert len(d3["items"]) == 1


def test_audit_logs_filters(client: TestClient, sqlite_db_session):
    """Test that entity_type and action_type optional filters work."""
    tenant = Tenant(tenant_id="TENANT_FILT", name="Pharmacy Fil")
    sqlite_db_session.add(tenant)

    sqlite_db_session.add_all([
        AuditLogModel(id=200, tenant_id="TENANT_FILT", entity_type="purchase_order",
                       entity_id="PO-F-001", action_type="CREATE", old_value=None, new_value=None,
                       extra_metadata=None, timestamp=datetime.now()),
        AuditLogModel(id=201, tenant_id="TENANT_FILT", entity_type="purchase_order",
                       entity_id="PO-F-001", action_type="UPDATE", old_value=None, new_value=None,
                       extra_metadata=None, timestamp=datetime.now()),
        AuditLogModel(id=202, tenant_id="TENANT_FILT", entity_type="medication_batch",
                       entity_id="MB-F-001", action_type="CREATE", old_value=None, new_value=None,
                       extra_metadata=None, timestamp=datetime.now()),
    ])
    sqlite_db_session.commit()

    # Filter by entity_type only
    r1 = client.get("/api/v1/audit-logs?entity_type=purchase_order",
                     headers={"X-Tenant-ID": "TENANT_FILT"})
    assert r1.json()["total"] == 2

    # Filter by action_type only
    r2 = client.get("/api/v1/audit-logs?action_type=CREATE",
                     headers={"X-Tenant-ID": "TENANT_FILT"})
    assert r2.json()["total"] == 2

    # Filter by both
    r3 = client.get("/api/v1/audit-logs?entity_type=purchase_order&action_type=UPDATE",
                     headers={"X-Tenant-ID": "TENANT_FILT"})
    assert r3.json()["total"] == 1
    assert r3.json()["items"][0]["entity_id"] == "PO-F-001"
