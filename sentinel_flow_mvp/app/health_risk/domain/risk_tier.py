"""
Risk tier classification — the human-facing severity label for a risk score.

WHY A SEPARATE MODULE (mirrors weather_anomaly.py):
The score is a continuous 0-100 float. Tiering is a value→label mapping
the API layer needs, but it belongs in the domain so every consumer
(router, future endpoints) uses the SAME boundaries. One function, one
source of truth — no duplicated threshold logic anywhere else.
"""

from enum import Enum


class RiskTier(str, Enum):
    """
    Human-readable severity band for a risk score.

    String-backed (str, Enum) so the .value is directly serialisable,
    matching the codebase's convention for categorical values.
    """

    LOW = "Low"
    MODERATE = "Moderate"
    HIGH = "High"
    SEVERE = "Severe"


# ---------------------------------------------------------------------------
# Tier boundaries.
#
# HONESTY CAVEAT: these ceilings are a product decision, not derived from
# outcome data — the formula itself is uncalibrated (see
# docs/health_risk_backtest_2026.md), so these are qualitative bands only.
#
# .9 ceilings rather than integers because score is a rounded float that
# can carry one decimal — 39.9 vs 40.0 must resolve unambiguously.
# ---------------------------------------------------------------------------
LOW_TIER_MAX = 39.9
MODERATE_TIER_MAX = 59.9
HIGH_TIER_MAX = 79.9
# Anything above HIGH_TIER_MAX (80.0-100.0) is SEVERE.


def compute_risk_tier(score: float) -> RiskTier:
    """
    Map a 0-100 risk score to its severity tier.

    Bands:
      Low:      0.0-39.9
      Moderate: 40.0-59.9
      High:     60.0-79.9
      Severe:   80.0-100.0
    """
    if score <= LOW_TIER_MAX:
        return RiskTier.LOW
    if score <= MODERATE_TIER_MAX:
        return RiskTier.MODERATE
    if score <= HIGH_TIER_MAX:
        return RiskTier.HIGH
    return RiskTier.SEVERE
