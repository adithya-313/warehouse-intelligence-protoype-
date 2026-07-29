"""
Tests for the health_risk feature flag gate.

These tests prove the AND-gate behaviour of the two-flag system:
  global=True  + tenant=True  → True
  global=True  + tenant=False → False
  global=False + tenant=True  → False
  global=False + tenant=False → False

We use MagicMock for both Tenant and ApplicationSettings because:
  - Tenant is a SQLAlchemy model that requires a database to construct.
  - ApplicationSettings reads from environment variables on init.
  Mocks let us test the logic in isolation, in milliseconds, with no DB.
"""

from unittest.mock import MagicMock

from app.health_risk.infrastructure.feature_flag import is_health_risk_enabled


class TestFeatureFlagAndGate:
    """The feature flag must return True ONLY when both flags are True."""

    def test_both_true_returns_true(self) -> None:
        """global=True + tenant=True → True (scoring should run)."""
        settings = MagicMock()
        settings.HEALTH_RISK_ENABLED = True

        tenant = MagicMock()
        tenant.health_risk_enabled = True

        assert is_health_risk_enabled(tenant, settings) is True

    def test_global_true_tenant_false_returns_false(self) -> None:
        """
        global=True + tenant=False → False.
        The global flag allows it, but this pharmacy hasn't opted in yet.
        """
        settings = MagicMock()
        settings.HEALTH_RISK_ENABLED = True

        tenant = MagicMock()
        tenant.health_risk_enabled = False

        assert is_health_risk_enabled(tenant, settings) is False

    def test_global_false_tenant_true_returns_false(self) -> None:
        """
        global=False + tenant=True → False.
        The pharmacy opted in, but the global kill switch is OFF.
        This could happen during an incident — safe, not a bug.
        """
        settings = MagicMock()
        settings.HEALTH_RISK_ENABLED = False

        tenant = MagicMock()
        tenant.health_risk_enabled = True

        assert is_health_risk_enabled(tenant, settings) is False

    def test_both_false_returns_false(self) -> None:
        """global=False + tenant=False → False (both disabled)."""
        settings = MagicMock()
        settings.HEALTH_RISK_ENABLED = False

        tenant = MagicMock()
        tenant.health_risk_enabled = False

        assert is_health_risk_enabled(tenant, settings) is False

    def test_global_default_is_false(self) -> None:
        """
        Explicit coverage: the default value of HEALTH_RISK_ENABLED
        in ApplicationSettings is False. We verify this by checking
        the Field definition directly.
        """
        from app.core.config import ApplicationSettings

        # Instantiate without environment variables — should get defaults
        default_settings = ApplicationSettings()
        assert default_settings.HEALTH_RISK_ENABLED is False
