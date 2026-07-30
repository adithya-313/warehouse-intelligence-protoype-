"""
Tests for the standalone /api/v1/health-risk/current, /history, and /explain endpoints.

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

from datetime import datetime, timedelta, timezone
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
    row_id: int | None = None,
    contributing_factors: dict | None = None,
) -> MagicMock:
    """Build a MagicMock that looks like a HealthRiskScoreModel ORM row."""
    row = MagicMock(spec=HealthRiskScoreModel)
    row.id = row_id
    row.pincode = pincode
    row.disease_category = disease
    row.score = score
    row.confidence = confidence
    row.computed_at = datetime.now(timezone.utc)
    row.contributing_factors = contributing_factors
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
        # Note: f.filter returns f itself so that calling .filter() multiple
        # times (as /history does for pincode + date range) still works.
        # f.first returns the first element of score_rows (or None if empty)
        # for the /explain endpoint which queries by id via .first().
        if model == HealthRiskScoreModel:
            q = MagicMock()
            f = MagicMock()
            o = MagicMock()
            o.all.return_value = score_rows
            f.order_by.return_value = o
            f.filter.return_value = f
            f.first.return_value = score_rows[0] if score_rows else None
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


class TestHealthRiskHistoryEndpoint:
    """
    Tests for GET /api/v1/health-risk/history.
    """

    def test_tenant_with_five_score_rows_across_different_days_returns_all_five_ordered_oldest_first(
        self, app: FastAPI, client: TestClient
    ):
        """
        Tenant has 5 HealthRiskScoreModel rows across different days
        within a 30-day range → endpoint returns all 5, ordered oldest
        to newest (ascending computed_at). No deduplication.
        """
        # Arrange: a tenant with a pincode
        mock_tenant = MagicMock(spec=Tenant)
        mock_tenant.pincode = "682001"

        # Five score rows across different days (simulating a time series)
        base_time = datetime.now(timezone.utc)
        score_rows = [
            _make_health_risk_score_row(score=10.0, disease="DENGUE"),
            _make_health_risk_score_row(score=20.0, disease="DENGUE"),
            _make_health_risk_score_row(score=30.0, disease="DENGUE"),
            _make_health_risk_score_row(score=40.0, disease="LEPTOSPIROSIS"),
            _make_health_risk_score_row(score=50.0, disease="LEPTOSPIROSIS"),
        ]
        # Set computed_at on each row so ordering is predictable:
        # oldest first, newest last.
        score_rows[0].computed_at = base_time - timedelta(days=4)
        score_rows[1].computed_at = base_time - timedelta(days=3)
        score_rows[2].computed_at = base_time - timedelta(days=2)
        score_rows[3].computed_at = base_time - timedelta(days=1)
        score_rows[4].computed_at = base_time

        mock_session = _build_mock_session(tenant=mock_tenant, score_rows=score_rows)

        app.dependency_overrides[get_database_session] = lambda: mock_session
        app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

        # Act
        response = client.get("/api/v1/health-risk/history?days=30")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["pincode"] == "682001"
        assert data["days"] == 30
        assert len(data["scores"]) == 5

        # Scores should be ordered oldest first (ascending computed_at)
        timestamps = [s["computed_at"] for s in data["scores"]]
        assert timestamps == sorted(timestamps), (
            "Scores must be ordered oldest first for time-series display."
        )

        # Verify score values are in ascending order matching our setup
        score_values = [s["score"] for s in data["scores"]]
        assert score_values == [10.0, 20.0, 30.0, 40.0, 50.0]

    def test_tenant_with_zero_score_rows_returns_empty_list(
        self, app: FastAPI, client: TestClient
    ):
        """
        Tenant has a pincode but no score rows in the date range
        → endpoint returns 200 with an empty scores list (not an error).
        Same cold-start behaviour as /current.
        """
        # Arrange: tenant exists but no HealthRiskScoreModel rows
        mock_tenant = MagicMock(spec=Tenant)
        mock_tenant.pincode = "682001"

        mock_session = _build_mock_session(tenant=mock_tenant, score_rows=[])

        app.dependency_overrides[get_database_session] = lambda: mock_session
        app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

        # Act
        response = client.get("/api/v1/health-risk/history?days=30")

        # Assert: 200 with empty scores, not a 404 or 500
        assert response.status_code == 200
        data = response.json()
        assert data["pincode"] == "682001"
        assert data["days"] == 30
        assert data["scores"] == []

    def test_days_equals_zero_returns_400(
        self, app: FastAPI, client: TestClient
    ):
        """
        days=0 is outside the valid range (1-365) → endpoint returns
        400 with a clear error message.
        """
        # Arrange: tenant exists so we get past the tenant check
        mock_tenant = MagicMock(spec=Tenant)
        mock_tenant.pincode = "682001"

        mock_session = _build_mock_session(tenant=mock_tenant, score_rows=[])

        app.dependency_overrides[get_database_session] = lambda: mock_session
        app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

        # Act
        response = client.get("/api/v1/health-risk/history?days=0")

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert "days" in data["detail"].lower()

    def test_days_negative_returns_400(
        self, app: FastAPI, client: TestClient
    ):
        """
        days=-5 is negative → endpoint returns 400.
        """
        # Arrange
        mock_tenant = MagicMock(spec=Tenant)
        mock_tenant.pincode = "682001"

        mock_session = _build_mock_session(tenant=mock_tenant, score_rows=[])

        app.dependency_overrides[get_database_session] = lambda: mock_session
        app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

        # Act
        response = client.get("/api/v1/health-risk/history?days=-5")

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert "days" in data["detail"].lower()

    def test_days_exceeds_maximum_returns_400(
        self, app: FastAPI, client: TestClient
    ):
        """
        days=9999 exceeds the maximum of 365 → endpoint returns 400.
        This prevents absurdly large date ranges that would pull
        gigabytes of data.
        """
        # Arrange
        mock_tenant = MagicMock(spec=Tenant)
        mock_tenant.pincode = "682001"

        mock_session = _build_mock_session(tenant=mock_tenant, score_rows=[])

        app.dependency_overrides[get_database_session] = lambda: mock_session
        app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

        # Act
        response = client.get("/api/v1/health-risk/history?days=9999")

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert "days" in data["detail"].lower()

    def test_days_omitted_defaults_to_30(
        self, app: FastAPI, client: TestClient
    ):
        """
        No days query param sent → defaults to 30 and still works.
        """
        # Arrange
        mock_tenant = MagicMock(spec=Tenant)
        mock_tenant.pincode = "682001"

        score_rows = [
            _make_health_risk_score_row(score=75.0, disease="DENGUE"),
        ]

        mock_session = _build_mock_session(tenant=mock_tenant, score_rows=score_rows)

        app.dependency_overrides[get_database_session] = lambda: mock_session
        app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

        # Act — no days param
        response = client.get("/api/v1/health-risk/history")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["days"] == 30
        assert len(data["scores"]) == 1

    def test_tenant_with_no_pincode_returns_404(
        self, app: FastAPI, client: TestClient
    ):
        """
        Tenant row exists but pincode is None → endpoint returns 404.
        Same check and message as /current.
        """
        # Arrange: tenant exists but has no pincode
        mock_tenant = MagicMock(spec=Tenant)
        mock_tenant.pincode = None

        mock_session = _build_mock_session(tenant=mock_tenant, score_rows=[])

        app.dependency_overrides[get_database_session] = lambda: mock_session
        app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

        # Act
        response = client.get("/api/v1/health-risk/history")

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert "pincode" in data["detail"].lower()


class TestHealthRiskExplainEndpoint:
    """
    Tests for GET /api/v1/health-risk/explain/{score_id}.
    """

    def test_score_belongs_to_calling_tenant_returns_full_breakdown(
        self, app: FastAPI, client: TestClient
    ):
        """
        Score row exists and its pincode matches the calling tenant's
        pincode → endpoint returns 200 with all fields including the
        full contributing_factors dict.
        """
        # Arrange: a tenant with a pincode
        mock_tenant = MagicMock(spec=Tenant)
        mock_tenant.pincode = "682001"

        # One score row with all fields populated, including
        # contributing_factors (the actual dict stored by the scorer).
        score_rows = [
            _make_health_risk_score_row(
                score=85.0,
                disease="DENGUE",
                pincode="682001",
                row_id=42,
                contributing_factors={
                    "trend_score": 82.0,
                    "humidity_percent": 91.0,
                    "rain_mm": 12.0,
                    "weather_anomaly": 90.0,
                },
            ),
        ]

        mock_session = _build_mock_session(tenant=mock_tenant, score_rows=score_rows)

        app.dependency_overrides[get_database_session] = lambda: mock_session
        app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

        # Act
        response = client.get("/api/v1/health-risk/explain/42")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 42
        assert data["pincode"] == "682001"
        assert data["disease_category"] == "DENGUE"
        assert data["score"] == 85.0
        assert data["confidence"] == "real_data"
        assert "computed_at" in data

        # contributing_factors must contain ONLY the 4 real keys stored
        # by TransparentFormulaScorer — no invented or extra fields.
        assert data["contributing_factors"] == {
            "trend_score": 82.0,
            "humidity_percent": 91.0,
            "rain_mm": 12.0,
            "weather_anomaly": 90.0,
        }

    def test_score_id_does_not_exist_returns_404(
        self, app: FastAPI, client: TestClient
    ):
        """
        No score row with the given id exists → endpoint returns 404
        with message "Health risk score not found."
        """
        # Arrange: tenant exists but score_rows is empty (no rows at all)
        mock_tenant = MagicMock(spec=Tenant)
        mock_tenant.pincode = "682001"

        mock_session = _build_mock_session(tenant=mock_tenant, score_rows=[])

        app.dependency_overrides[get_database_session] = lambda: mock_session
        app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

        # Act
        response = client.get("/api/v1/health-risk/explain/999")

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Health risk score not found."

    def test_score_exists_but_belongs_to_different_pincode_returns_404(
        self, app: FastAPI, client: TestClient
    ):
        """
        Score row EXISTS with the given id but its pincode differs from
        the calling tenant's pincode → endpoint returns 404 with the
        IDENTICAL message as "id not found" — preventing an attacker
        from distinguishing "doesn't exist" from "not yours."
        """
        # Arrange: tenant has pincode "682001"
        mock_tenant = MagicMock(spec=Tenant)
        mock_tenant.pincode = "682001"

        # The score row has a DIFFERENT pincode "682002" — it belongs
        # to a different pharmacy.
        score_rows = [
            _make_health_risk_score_row(
                score=85.0,
                disease="DENGUE",
                pincode="682002",  # Different pincode!
                row_id=99,
                contributing_factors={
                    "trend_score": 82.0,
                    "humidity_percent": 91.0,
                    "rain_mm": 12.0,
                    "weather_anomaly": 90.0,
                },
            ),
        ]

        mock_session = _build_mock_session(tenant=mock_tenant, score_rows=score_rows)

        app.dependency_overrides[get_database_session] = lambda: mock_session
        app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

        # Act
        response = client.get("/api/v1/health-risk/explain/99")

        # Assert: 404 with the EXACT SAME message as the "id doesn't exist" test.
        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Health risk score not found."

    def test_calling_tenant_has_no_pincode_returns_404(
        self, app: FastAPI, client: TestClient
    ):
        """
        Tenant row exists but pincode is None → endpoint returns 404.
        Same check and message as /current and /history.
        """
        # Arrange: tenant exists but has no pincode
        mock_tenant = MagicMock(spec=Tenant)
        mock_tenant.pincode = None

        mock_session = _build_mock_session(tenant=mock_tenant, score_rows=[])

        app.dependency_overrides[get_database_session] = lambda: mock_session
        app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

        # Act
        response = client.get("/api/v1/health-risk/explain/42")

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert "pincode" in data["detail"].lower()

    def test_missing_x_tenant_id_header_returns_403(
        self, app: FastAPI, client: TestClient
    ):
        """
        No X-Tenant-ID header sent → get_current_tenant dependency raises
        HTTPException(403), which FastAPI converts to a 403 response.
        Same behaviour as /current and /history.
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
        response = client.get("/api/v1/health-risk/explain/42")

        # Assert
        assert response.status_code == 403
