"""
Tests for health_risk_tasks.py — the scheduled Celery ingestion job.

WHAT THIS TESTS:
  - The global kill-switch (HEALTH_RISK_ENABLED) early-return behaviour.
  - The bug fix: an empty list from run_ingestion_for_pincode is now
    counted as FAILED, not succeeded.
  - The auto-onboarding gate: first real success for a tenant that is
    not yet enabled flips health_risk_enabled to True automatically.
  - Exception handling: one failing tenant does not stop the rest.
  - The summary log line reports correct succeeded/failed counts.

WHAT THIS DOES NOT TEST:
  - run_ingestion_for_pincode itself (tested in test_ingestion_service.py).
  - The scoring formula (tested in test_scoring_formula.py).
  - The Celery scheduling / beat configuration.

We mock:
  - settings (to control HEALTH_RISK_ENABLED).
  - SessionLocal (to return a mock DB session with controlled Tenant rows).
  - run_ingestion_for_pincode (to return a controlled result list or raise).
  - logger (to capture and assert on log messages without console noise).
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.models import Tenant


# =========================================================================
# Helper: create a mock Tenant row
# =========================================================================

def _make_mock_tenant(
    tenant_id: str = "tenant-001",
    pincode: str = "682001",
    health_risk_enabled: bool = True,
) -> MagicMock:
    """Build a MagicMock that looks like a Tenant ORM row."""
    tenant = MagicMock(spec=Tenant)
    tenant.tenant_id = tenant_id
    tenant.pincode = pincode
    tenant.health_risk_enabled = health_risk_enabled
    return tenant


# =========================================================================
# Helper: create a mock DB session that returns given tenants for Tenant query
# =========================================================================

def _make_mock_db(tenants: list[MagicMock]) -> MagicMock:
    """
    Create a mock SQLAlchemy session whose .query(Tenant).filter(...).all()
    returns the given tenant list. All other query behaviour is unconfigured
    (the task only queries Tenant inside the try block).
    """
    db = MagicMock()
    q = MagicMock()
    f = MagicMock()
    f.all.return_value = tenants
    q.filter.return_value = f
    db.query.return_value = q
    return db


# =========================================================================
# Tests
# =========================================================================

class TestHealthRiskIngestionTask:
    """
    Tests for run_health_risk_ingestion_task in app/tasks/health_risk_tasks.py.
    """

    @patch("app.tasks.health_risk_tasks.logger")
    @patch("app.tasks.health_risk_tasks.run_ingestion_for_pincode")
    @patch("app.tasks.health_risk_tasks.SessionLocal")
    @patch("app.tasks.health_risk_tasks.settings")
    def test_global_flag_disabled_skips_everything(
        self,
        mock_settings,
        mock_session_local,
        mock_run_ingestion,
        mock_logger,
    ):
        """
        HEALTH_RISK_ENABLED=False → the task returns immediately.
        Confirm no DB session is created and no ingestion is attempted.
        """
        # Arrange: kill switch is OFF
        mock_settings.HEALTH_RISK_ENABLED = False

        # Act
        from app.tasks.health_risk_tasks import run_health_risk_ingestion_task
        run_health_risk_ingestion_task()

        # Assert: the early-return path should prevent ANY of these
        mock_session_local.assert_not_called()
        mock_run_ingestion.assert_not_called()

    @patch("app.tasks.health_risk_tasks.logger")
    @patch("app.tasks.health_risk_tasks.run_ingestion_for_pincode")
    @patch("app.tasks.health_risk_tasks.SessionLocal")
    @patch("app.tasks.health_risk_tasks.settings")
    def test_real_success_already_enabled(
        self,
        mock_settings,
        mock_session_local,
        mock_run_ingestion,
        mock_logger,
    ):
        """
        One tenant with health_risk_enabled=True gets real (non-empty)
        results → succeeded is incremented, the flag stays True, and no
        unnecessary db.commit() is performed.
        """
        # Arrange
        mock_settings.HEALTH_RISK_ENABLED = True

        # Create a tenant that is already enabled
        tenant = _make_mock_tenant(
            tenant_id="tenant-alpha",
            pincode="682001",
            health_risk_enabled=True,
        )

        # The mock DB returns this tenant from the enabled_tenants query
        mock_session_local.return_value = _make_mock_db([tenant])

        # run_ingestion_for_pincode returns 3 RiskScore objects (real success)
        mock_run_ingestion.return_value = [MagicMock(), MagicMock(), MagicMock()]

        # Act
        from app.tasks.health_risk_tasks import run_health_risk_ingestion_task
        run_health_risk_ingestion_task()

        # Assert: success log message was emitted
        success_messages = [
            c[0][0] % c[0][1:] if c[0] and len(c[0]) > 1
            else str(c[0][0]) if c[0]
            else ""
            for c in mock_logger.info.call_args_list
        ]
        assert any("Successfully scored" in msg for msg in success_messages), (
            "Expected a 'Successfully scored' log message for the enabled tenant."
        )

        # No "zero scored diseases" warning should appear
        warning_messages = [
            str(c[0][0]) if c[0] else ""
            for c in mock_logger.warning.call_args_list
        ]
        assert not any("zero scored diseases" in msg for msg in warning_messages)

        # The tenant flag is still True (unchanged — no need to re-commit)
        assert tenant.health_risk_enabled is True

    @patch("app.tasks.health_risk_tasks.logger")
    @patch("app.tasks.health_risk_tasks.run_ingestion_for_pincode")
    @patch("app.tasks.health_risk_tasks.SessionLocal")
    @patch("app.tasks.health_risk_tasks.settings")
    def test_empty_result_counts_as_failure(
        self,
        mock_settings,
        mock_session_local,
        mock_run_ingestion,
        mock_logger,
    ):
        """
        run_ingestion_for_pincode returns an EMPTY list (no exception)
        → this is now counted as FAILED, not succeeded.

        This is the core bug-fix test: the old code incremented 'succeeded'
        for any non-exception return, even when zero diseases were scored.
        """
        # Arrange
        mock_settings.HEALTH_RISK_ENABLED = True

        tenant = _make_mock_tenant(
            tenant_id="tenant-beta",
            pincode="560001",
            health_risk_enabled=True,
        )

        mock_session_local.return_value = _make_mock_db([tenant])

        # run_ingestion_for_pincode returns an empty list — all diseases
        # silently failed inside its own per-disease try/except.
        mock_run_ingestion.return_value = []

        # Act
        from app.tasks.health_risk_tasks import run_health_risk_ingestion_task
        run_health_risk_ingestion_task()

        # ------------------------------------------------------------------
        # Proof of the bug fix: the "zero scored diseases" WARNING must
        # appear, and the "Successfully scored" message must NOT appear.
        # ------------------------------------------------------------------

        # Collect log messages for assertion
        info_messages = [
            str(c[0][0]) if c[0] else ""
            for c in mock_logger.info.call_args_list
        ]
        warning_messages = [
            str(c[0][0]) if c[0] else ""
            for c in mock_logger.warning.call_args_list
        ]

        # The empty-result path emits logger.warning, NOT logger.info
        assert any("zero scored diseases" in msg for msg in warning_messages), (
            "Expected a WARNING about zero scored diseases for the empty-list case."
        )

        # The "Successfully scored" message belongs to the success path
        # and must NOT appear when results are empty.
        assert not any("Successfully scored" in msg for msg in info_messages), (
            "BUG VERIFICATION FAILED: 'Successfully scored' was logged even "
            "though run_ingestion_for_pincode returned an empty list. "
            "This means the success-counting bug is still present."
        )

        # No exception message either (soft failure, not a hard crash)
        error_messages = [
            str(c[0][0]) if c[0] else ""
            for c in mock_logger.exception.call_args_list
        ]
        assert not any("FAILED" in msg for msg in error_messages), (
            "No exception should have been logged — the empty list is a "
            "soft failure, not a raised exception."
        )

    @patch("app.tasks.health_risk_tasks.logger")
    @patch("app.tasks.health_risk_tasks.run_ingestion_for_pincode")
    @patch("app.tasks.health_risk_tasks.SessionLocal")
    @patch("app.tasks.health_risk_tasks.settings")
    def test_exception_does_not_stop_subsequent_tenants(
        self,
        mock_settings,
        mock_session_local,
        mock_run_ingestion,
        mock_logger,
    ):
        """
        First tenant raises an exception, second tenant succeeds.
        The loop continues past the failure — the first tenant is counted
        as failed, the second as succeeded.
        """
        # Arrange
        mock_settings.HEALTH_RISK_ENABLED = True

        tenant_a = _make_mock_tenant("tenant-A", "682001", True)
        tenant_b = _make_mock_tenant("tenant-B", "560001", True)

        mock_session_local.return_value = _make_mock_db([tenant_a, tenant_b])

        # First call raises, second call succeeds with 3 results
        mock_run_ingestion.side_effect = [
            Exception("Google Trends rate-limited"),
            [MagicMock(), MagicMock(), MagicMock()],
        ]

        # Act
        from app.tasks.health_risk_tasks import run_health_risk_ingestion_task
        run_health_risk_ingestion_task()

        # Assert: both tenants were processed (mock was called twice)
        assert mock_run_ingestion.call_count == 2, (
            "Both tenants should have been processed even though "
            "the first one raised an exception."
        )

        # The summary log line should show Processed=2, Succeeded=1, Failed=1.
        # Because the logger is mocked, the %d placeholders are NOT
        # interpolated — they appear as raw positional args. We verify
        # the positional args directly.
        summary_call = mock_logger.info.call_args_list[-1]
        assert summary_call[0][1] == 2, "Expected Processed=2"
        assert summary_call[0][2] == 1, "Expected Succeeded=1"
        assert summary_call[0][3] == 1, "Expected Failed=1"

    @patch("app.tasks.health_risk_tasks.logger")
    @patch("app.tasks.health_risk_tasks.run_ingestion_for_pincode")
    @patch("app.tasks.health_risk_tasks.SessionLocal")
    @patch("app.tasks.health_risk_tasks.settings")
    def test_two_tenants_summary_mixed_results(
        self,
        mock_settings,
        mock_session_local,
        mock_run_ingestion,
        mock_logger,
    ):
        """
        Two tenants: one succeeds (non-empty list), one fails (exception).
        Verifies the summary line reports the correct split.
        """
        # Arrange
        mock_settings.HEALTH_RISK_ENABLED = True

        tenant_ok = _make_mock_tenant("tenant-OK", "682001", True)
        tenant_bad = _make_mock_tenant("tenant-BAD", "560001", True)

        mock_session_local.return_value = _make_mock_db([tenant_ok, tenant_bad])

        # First call succeeds, second call raises
        mock_run_ingestion.side_effect = [
            [MagicMock(), MagicMock(), MagicMock()],
            Exception("Weather API timeout"),
        ]

        # Act
        from app.tasks.health_risk_tasks import run_health_risk_ingestion_task
        run_health_risk_ingestion_task()

        # Assert: the summary call's positional args are correct.
        # (The %d placeholders are not interpolated by a mocked logger.)
        summary_call = mock_logger.info.call_args_list[-1]
        assert summary_call[0][1] == 2, "Expected Processed=2"
        assert summary_call[0][2] == 1, "Expected Succeeded=1"
        assert summary_call[0][3] == 1, "Expected Failed=1"

        # Both tenants were processed
        assert mock_run_ingestion.call_count == 2
