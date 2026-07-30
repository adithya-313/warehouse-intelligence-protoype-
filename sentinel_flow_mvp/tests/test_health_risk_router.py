"""
Tests for the standalone /api/v1/health-risk/current endpoint.

WHY A SEPARATE TEST FILE (NOT ADDING TO test_procurement_router_health_risk.py):
The procurement_router tests mix health-risk logic with alert-generation
and feature-flag mocks. This file tests the clean read-only endpoint in
isolation — just the "give me my current risk scores" query, no alerts,
no notifications, no feature flags.

We duplicate the _make_health_risk_score_row helper here (rather than
importing from test_procurement_router_health_risk.py) because importing
from one test file into another is fragile — pytest discovery order is
unpredictable and the source file's module-level mocks (_MOCK_MED, etc.)
are irrelevant here.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_tenant
from app.api.v1.health_risk_router import router
from app.health_risk.infrastructure.db_models import HealthRiskScoreModel
from app.infrastructure.database import get_database_session
from app.infrastructure.models import Tenant


# =========================================================================
# Helper: create a HealthRiskScoreModel row (like what the DB returns)
# =========================================================================
# Duplicated from test_procurement_router_health_risk.py (same author,
# same pattern) to keep this test file self-contained and avoid fragile
# cross-test-file imports.

def _make_health_risk_score_row(
    score: float,
    disease: str = "DENGUE",
    pincode: str = "682001",
    confidence: str = "real_data",
) -> MagicMock:
    """Build a MagicMock that looks like a HealthRiskScoreModel ORM row."""
    row = MagicMock(spec=HealthRiskScoreModel)
    row.pincode = pincode
    row.disease_category = disease
    row.score = score
    row.confidence = confidence
    row.computed_at = datetime.now(timezone.utc)
    return row


# =========================================================================
# Helper: build a mock session that handles Tenant + HealthRiskScoreModel
# =========================================================================

def _build_mock_session(
    tenant: MagicMock | None,
    score_rows: list[MagicMock],
) -> MagicMock:
    """
    Returns a MagicMock session whose .query() dispatches correctly for
    Tenant lookups and HealthRiskScoreModel queries.

    tenant:     the MagicMock to return from query(Tenant).filter(...).first()
                or None to simulate "tenant not found".
    score_rows: the list of MagicMock rows to return from
                query(HealthRiskScoreModel).filter(...).order_by(...).all().
    """
    session = MagicMock()

    def query_side_effect(model):
        # --- Tenant query: db.query(Tenant).filter(...).first() ---
        if model == Tenant:
            q = MagicMock()
            f = MagicMock()
            f.first.return_value = tenant
            q.filter.return_value = f
            return q

        # --- HealthRiskScoreModel query: .filter(...).order_by(...).all() ---
        if model == HealthRiskScoreModel:
            q = MagicMock()
            f = MagicMock()
            o = MagicMock()
            o.all.return_value = score_rows
            f.order_by.return_value = o
            q.filter.return_value = f
            return q

        # --- Fallback for any other model ---
        return MagicMock()

    session.query.side_effect = query_side_effect
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.close = MagicMock()
    return session


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def app():
    """A fresh FastAPI instance with only the health-risk router."""
    _app = FastAPI()
    _app.include_router(router, prefix="/api/v1/health-risk")
    return _app


@pytest.fixture
def client(app):
    """TestClient bound to the fresh app (no dependency overrides yet)."""
    with TestClient(app) as c:
        yield c


# =========================================================================
# Tests
# =========================================================================


class TestHealthRiskCurrentEndpoint:
    """
    Tests for GET /api/v1/health-risk/current.
    """

    def test_tenant_with_two_disease_scores_returns_both(
        self, app: FastAPI, client: TestClient
    ):
        """
        Tenant has 2 HealthRiskScoreModel rows (DENGUE + LEPTOSPIROSIS)
        → endpoint returns both in the scores list with correct fields.
        """
        # Arrange: a tenant with a pincode
        mock_tenant = MagicMock(spec=Tenant)
        mock_tenant.pincode = "682001"

        # Two disease scores for this pincode
        score_rows = [
            _make_health_risk_score_row(score=85.0, disease="DENGUE"),
            _make_health_risk_score_row(score=92.0, disease="LEPTOSPIROSIS"),
        ]

        mock_session = _build_mock_session(tenant=mock_tenant, score_rows=score_rows)

        app.dependency_overrides[get_database_session] = lambda: mock_session
        app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

        # Act
        response = client.get("/api/v1/health-risk/current")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["pincode"] == "682001"
        assert len(data["scores"]) == 2

        # Both disease categories present
        diseases = {s["disease_category"] for s in data["scores"]}
        assert "DENGUE" in diseases
        assert "LEPTOSPIROSIS" in diseases

        # Each score has the expected fields and types
        for score in data["scores"]:
            assert "disease_category" in score
            assert "score" in score
            assert isinstance(score["score"], float)
            assert "confidence" in score
            assert "computed_at" in score

    def test_tenant_with_zero_scores_returns_empty_list(
        self, app: FastAPI, client: TestClient
    ):
        """
        Tenant has a pincode but the Celery background job hasn't run
        yet → endpoint returns 200 with an empty scores list (not an error).
        """
        # Arrange: tenant exists but no HealthRiskScoreModel rows
        mock_tenant = MagicMock(spec=Tenant)
        mock_tenant.pincode = "682001"

        mock_session = _build_mock_session(tenant=mock_tenant, score_rows=[])

        app.dependency_overrides[get_database_session] = lambda: mock_session
        app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

        # Act
        response = client.get("/api/v1/health-risk/current")

        # Assert: 200 with empty scores, not a 404 or 500
        assert response.status_code == 200
        data = response.json()
        assert data["pincode"] == "682001"
        assert data["scores"] == []

    def test_tenant_with_no_pincode_returns_404(
        self, app: FastAPI, client: TestClient
    ):
        """
        Tenant row exists but pincode is None/empty → endpoint returns
        404 with a clear message that pincode must be configured.
        """
        # Arrange: tenant exists but has no pincode
        mock_tenant = MagicMock(spec=Tenant)
        mock_tenant.pincode = None

        mock_session = _build_mock_session(tenant=mock_tenant, score_rows=[])

        app.dependency_overrides[get_database_session] = lambda: mock_session
        app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

        # Act
        response = client.get("/api/v1/health-risk/current")

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert "pincode" in data["detail"].lower()

    def test_tenant_not_found_returns_404(
        self, app: FastAPI, client: TestClient
    ):
        """
        Tenant row does not exist in database → endpoint returns 404.
        """
        # Arrange: tenant is None (not found)
        mock_session = _build_mock_session(tenant=None, score_rows=[])

        app.dependency_overrides[get_database_session] = lambda: mock_session
        app.dependency_overrides[get_current_tenant] = lambda: "nonexistent-tenant"

        # Act
        response = client.get("/api/v1/health-risk/current")

        # Assert
        assert response.status_code == 404

    def test_missing_x_tenant_id_header_returns_403(
        self, app: FastAPI, client: TestClient
    ):
        """
        No X-Tenant-ID header sent → get_current_tenant dependency raises
        HTTPException(403), which FastAPI converts to a 403 response.
        """
        # Arrange: override get_current_tenant with a function that always
        # raises 403, simulating what happens when the header is missing.
        def raise_403():
            raise HTTPException(
                status_code=403,
                detail="X-Tenant-ID header is missing. Access Denied.",
            )

        app.dependency_overrides[get_current_tenant] = raise_403
        app.dependency_overrides[get_database_session] = lambda: MagicMock()

        # Act — no X-Tenant-ID header sent
        response = client.get("/api/v1/health-risk/current")

        # Assert
        assert response.status_code == 403
