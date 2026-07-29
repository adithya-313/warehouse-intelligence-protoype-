"""
Feature flag gate for the health_risk scoring module.

WHY TWO FLAGS INSTEAD OF ONE:
A single flag (e.g. just a global boolean) would force every pharmacy
either on or off at the same time — no room for a phased rollout.

With TWO gates:

  Global flag (HEALTH_RISK_ENABLED in ApplicationSettings):
    Acts as the EMERGENCY STOP. If we discover a production bug (wrong
    scores, performance regression, data pipeline failure), we flip this
    to False and every pharmacy stops scoring immediately. No code deploy
    needed — just a config change.

  Per-pharmacy flag (Tenant.health_risk_enabled):
    Controls which individual pharmacy gets scoring. We enable one
    pharmacy, monitor for a week, then enable the next. This is the
    PILOT ROLLOUT mechanism.

Both must be True for scoring to run:
    is_enabled = global_flag AND tenant_flag

On the day every pharmacy is enabled, the tenant flag can be retired
(but the global flag stays as an emergency kill switch forever).
"""

from app.core.config import ApplicationSettings
from app.infrastructure.models import Tenant


def is_health_risk_enabled(
    tenant: Tenant,
    settings: ApplicationSettings,
) -> bool:
    """
    Returns True only if BOTH the global and per-pharmacy flags are True.

    This is a strict AND gate:
        True  + True   → True   (enabled, all conditions met)
        False + True   → False  (global kill switch is OFF)
        True  + False  → False  (this pharmacy not yet opted in)
        False + False  → False  (both disabled)

    Args:
        tenant:   The pharmacy/organisation whose flag to check.
        settings: The application-wide settings (with global flag).

    Returns:
        True if scoring should run for this tenant, False otherwise.
    """
    # ------------------------------------------------------------------
    # AND gate: both flags must be True.
    # If either is False, the module is disabled for this pharmacy.
    # ------------------------------------------------------------------
    return bool(settings.HEALTH_RISK_ENABLED and tenant.health_risk_enabled)
