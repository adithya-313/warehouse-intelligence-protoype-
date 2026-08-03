"""
Tests for the health_risk wiring in procurement_router.py.

WHAT THIS TESTS:
  The feature-flag gate added to get_disease_wave_alerts(). When the
  flag is enabled, the endpoint reads pre-computed HealthRiskScoreModel
  rows from the database (populated by the background Celery job).
  When disabled, the endpoint returns an empty list — the old
  trend_score > 70.0 heuristic has been removed.

WHAT THIS DOES NOT TEST:
  - The ingestion service itself (tested in test_ingestion_service.py).
  - Google Trends fetching (tested in test_trend_fetcher.py).
  - The scoring formula (tested in test_scoring_formula.py).
  - The feature flag logic (tested in test_feature_flag.py).
  - The Celery background task (tested via integration tests).

We mock:
  - get_application_settings to control HEALTH_RISK_ENABLED.
  - The database session to return predictable HealthRiskScoreModel
    rows and SKU/supplier rows.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.health_risk.infrastructure.db_models import HealthRiskScoreModel


# =========================================================================
# Shared mock objects
# =========================================================================

_MOCK_MED = MagicMock()
_MOCK_MED.sku_id = "PARA-001"

_MOCK_SUPPLIER = MagicMock()
_MOCK_SUPPLIER.supplier_id = "SUPP-BEST-001"

# =========================================================================
# Helper: create a HealthRiskScoreModel row (like what the DB returns)
# =========================================================================

def _make_health_risk_score_row(
    score: float,
    disease: str = "DENGUE",
    pincode: str = "682001",
    confidence: str = "real_data",
    row_id: int = 1,
) -> MagicMock:
    """Build a MagicMock that looks like a HealthRiskScoreModel ORM row."""
    row = MagicMock(spec=HealthRiskScoreModel)
    row.id = row_id
    row.pincode = pincode
    row.disease_category = disease
    row.score = score
    row.confidence = confidence
    row.computed_at = datetime.now(timezone.utc)
    return row


# A shared list of score rows that tests can mutate.
_HEALTH_RISK_SCORE_ROWS: list[MagicMock] = []


def _build_query_side_effect(extra_overrides=None):
    """
    Returns a side_effect for mock_session.query that handles BOTH:
      - Single-model:   db.query(Model)          → .filter().first(), .order_by().first()
      - Multi-column:   db.query(Model.col, ...) → .filter().group_by().order_by().first()

    The default config returns empty results for all non-overridden models.
    extra_overrides: optional callable(model) that can override the mock for specific models.
    """
    def side_effect(*args):
        # --- Multi-column projection: db.query(Model.col, func.count(...)) ---
        if len(args) > 1 or (len(args) == 1 and not isinstance(args[0], type)):
            q = MagicMock()
            f = MagicMock()
            g = MagicMock()
            ordered = MagicMock()
            ordered.first.return_value = _MOCK_SUPPLIER
            g.order_by.return_value = ordered
            f.group_by.return_value = g
            q.filter.return_value = f
            return q

        # --- Single-model query: db.query(Model) ---
        model = args[0]
        q = MagicMock()
        f = MagicMock()
        f.first.return_value = None          # default .filter(...).first()
        q.filter.return_value = f
        q.first.return_value = None          # default .first() (no filter)

        o = MagicMock()
        o.first.return_value = None  # .order_by(...).first() → no result by default
        q.order_by.return_value = o

        # Model-specific overrides
        if hasattr(model, '__name__'):
            name = model.__name__
            if name == "MedicationModel":
                f.first.return_value = None   # .filter(ilike("%para%")).first() → None
                q.first.return_value = _MOCK_MED  # .first() → mock med (fallback)
            elif name == "NotificationModel":
                f.first.return_value = None   # no existing notification today
            elif name == "HealthRiskScoreModel":
                # The endpoint chain: .query(Model).filter(...).order_by(...).all()
                # .order_by() is called on f (the filter mock).
                o = MagicMock()
                o.all.return_value = _HEALTH_RISK_SCORE_ROWS
                f.order_by.return_value = o

        # Allow per-test overrides
        if extra_overrides:
            extra_overrides(model, q, f)

        return q
    return side_effect


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture
def mock_session():
    """
    Creates a mock SQLAlchemy session with smart query dispatching.
    """
    session = MagicMock(spec=Session)
    session.query.side_effect = _build_query_side_effect()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.close = MagicMock()
    return session


@pytest.fixture
def procurement_client(mock_session):
    """
    FastAPI TestClient with ONLY the procurement router and overridden
    database + tenant dependencies.
    """
    from app.api.v1.procurement_router import router
    from app.infrastructure.database import get_database_session
    from app.api.dependencies import get_current_tenant

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_database_session] = lambda: mock_session
    app.dependency_overrides[get_current_tenant] = lambda: "test-tenant-001"

    with TestClient(app) as client:
        yield client


# =========================================================================
# Helper: override Tenant query return value
# =========================================================================

def _configure_tenant_query(mock_session, mock_tenant):
    """
    Wraps the existing query side_effect so that db.query(Tenant).filter(...).first()
    returns mock_tenant, while all other model queries keep their default behavior.
    """
    original_side_effect = mock_session.query.side_effect

    def tenant_aware_side_effect(*args):
        if len(args) == 1 and isinstance(args[0], type) and args[0].__name__ == "Tenant":
            q = MagicMock()
            f = MagicMock()
            f.first.return_value = mock_tenant
            q.filter.return_value = f
            return q
        return original_side_effect(*args)

    mock_session.query.side_effect = tenant_aware_side_effect


# =========================================================================
# Tests
# =========================================================================


class TestProcurementHealthRiskFlag:
    """
    Tests for the health_risk feature flag wiring.
    """

    @patch("app.api.v1.procurement_router.get_application_settings")
    def test_flag_disabled_returns_empty_list(
        self, mock_get_settings, procurement_client
    ):
        """
        HEALTH_RISK_ENABLED=False → return empty alerts immediately.
        The old trend_score > 70.0 heuristic has been removed.
        """
        # Arrange: feature flag OFF (default)
        mock_settings = MagicMock()
        mock_settings.HEALTH_RISK_ENABLED = False
        mock_get_settings.return_value = mock_settings

        # Act
        response = procurement_client.get("/procurement/disease-wave-alerts")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data == [], "Flag disabled → empty alerts, no legacy fallback"

    @patch("app.api.v1.procurement_router.get_application_settings")
    def test_flag_enabled_uses_health_risk_scores(
        self,
        mock_get_settings,
        procurement_client,
        mock_session,
    ):
        """
        Flag ON + DB has a high HealthRiskScoreModel row → alert with
        health_risk warning message (disease-specific).
        """
        # Arrange: feature flag ON
        mock_settings = MagicMock()
        mock_settings.HEALTH_RISK_ENABLED = True
        mock_get_settings.return_value = mock_settings

        # Populate the mock DB with one high-risk row (DENGUE, 85.0)
        _HEALTH_RISK_SCORE_ROWS.clear()
        _HEALTH_RISK_SCORE_ROWS.append(
            _make_health_risk_score_row(score=85.0, disease="DENGUE", row_id=1001),
        )

        # Make the Tenant query return a tenant with health_risk enabled + pincode
        mock_tenant = MagicMock()
        mock_tenant.health_risk_enabled = True
        mock_tenant.pincode = "682001"
        _configure_tenant_query(mock_session, mock_tenant)

        # Act
        response = procurement_client.get("/procurement/disease-wave-alerts")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1, "Health-risk path should produce at least one alert"
        # Warning message is disease-specific (not the legacy viral-fever message)
        assert "dengue" in data[0]["warning_message"].lower()
        assert "85" in data[0]["warning_message"]  # score is in the message
        # Hardcoded fields are preserved (with TODO comments)
        assert data[0]["probability_score"] == 0.89
        assert data[0]["expected_volume"] == 500

        # The DISEASE_WAVE notification deep-links to the score row that
        # triggered it (no second lookup needed).
        mock_session.add.assert_called_once()
        added_notification = mock_session.add.call_args.args[0]
        assert added_notification.health_risk_score_id == 1001

    @patch("app.api.v1.procurement_router.get_application_settings")
    def test_no_scores_yet_returns_empty_gracefully(
        self,
        mock_get_settings,
        procurement_client,
        mock_session,
    ):
        """
        Flag ON but HealthRiskScoreModel is empty (no DB rows yet)
        → empty list returned, no crash.
        """
        # Arrange: feature flag ON
        mock_settings = MagicMock()
        mock_settings.HEALTH_RISK_ENABLED = True
        mock_get_settings.return_value = mock_settings

        # No score rows in the mock DB (cold-start / first run)
        _HEALTH_RISK_SCORE_ROWS.clear()

        # Make the Tenant query return a tenant
        mock_tenant = MagicMock()
        mock_tenant.health_risk_enabled = True
        mock_tenant.pincode = "682001"
        _configure_tenant_query(mock_session, mock_tenant)

        # Act
        response = procurement_client.get("/procurement/disease-wave-alerts")

        # Assert: no crash, empty alerts
        assert response.status_code == 200
        data = response.json()
        assert data == [], "No scores in DB → empty alerts"

    @patch("app.api.v1.procurement_router.get_application_settings")
    def test_flag_enabled_no_high_risk_scores_returns_empty(
        self,
        mock_get_settings,
        procurement_client,
        mock_session,
    ):
        """
        Flag ON but all HealthRiskScoreModel rows are below threshold
        → empty alert list.
        """
        # Arrange: feature flag ON
        mock_settings = MagicMock()
        mock_settings.HEALTH_RISK_ENABLED = True
        mock_get_settings.return_value = mock_settings

        # All scores are low (below 70.0 threshold)
        _HEALTH_RISK_SCORE_ROWS.clear()
        _HEALTH_RISK_SCORE_ROWS.extend([
            _make_health_risk_score_row(score=30.0, disease="DENGUE"),
            _make_health_risk_score_row(score=45.0, disease="LEPTOSPIROSIS"),
            _make_health_risk_score_row(score=50.0, disease="VIRAL_FEVER"),
        ])

        mock_tenant = MagicMock()
        mock_tenant.health_risk_enabled = True
        mock_tenant.pincode = "682001"
        _configure_tenant_query(mock_session, mock_tenant)

        # Act
        response = procurement_client.get("/procurement/disease-wave-alerts")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data == [], "No scores >= 70.0 → no alerts"

    @patch("app.api.v1.procurement_router.get_application_settings")
    def test_flag_enabled_multiple_diseases_cross_threshold(
        self,
        mock_get_settings,
        procurement_client,
        mock_session,
    ):
        """
        Flag ON + multiple disease rows with scores >= 70.0 → one alert each.
        """
        # Arrange
        mock_settings = MagicMock()
        mock_settings.HEALTH_RISK_ENABLED = True
        mock_get_settings.return_value = mock_settings

        # Two diseases cross the threshold
        _HEALTH_RISK_SCORE_ROWS.clear()
        _HEALTH_RISK_SCORE_ROWS.extend([
            _make_health_risk_score_row(score=85.0, disease="DENGUE"),
            _make_health_risk_score_row(score=92.0, disease="LEPTOSPIROSIS"),
            _make_health_risk_score_row(score=45.0, disease="VIRAL_FEVER"),
        ])

        mock_tenant = MagicMock()
        mock_tenant.health_risk_enabled = True
        mock_tenant.pincode = "682001"
        _configure_tenant_query(mock_session, mock_tenant)

        # Act
        response = procurement_client.get("/procurement/disease-wave-alerts")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2, "Two diseases crossed threshold, expected 2 alerts"
        # Both disease names appear in warning messages
        messages = [a["warning_message"].lower() for a in data]
        assert any("dengue" in m for m in messages)
        assert any("leptospirosis" in m for m in messages)
        assert not any("viral_fever" in m for m in messages)
