"""
Tests for compute_risk_tier — pure value→label mapping, no mocking.

Covers one value in each of the four bands plus every boundary edge
(39.9/40.0, 59.9/60.0, 79.9/80.0) to prove there is no off-by-one gap
or overlap between adjacent tiers.
"""

from app.health_risk.domain.risk_tier import RiskTier, compute_risk_tier


class TestComputeRiskTier:
    """Known inputs, known expected labels — one value per band."""

    def test_low_band(self) -> None:
        assert compute_risk_tier(0.0) == RiskTier.LOW
        assert compute_risk_tier(20.0) == RiskTier.LOW

    def test_moderate_band(self) -> None:
        assert compute_risk_tier(40.0) == RiskTier.MODERATE
        assert compute_risk_tier(55.5) == RiskTier.MODERATE

    def test_high_band(self) -> None:
        assert compute_risk_tier(60.0) == RiskTier.HIGH
        assert compute_risk_tier(70.0) == RiskTier.HIGH

    def test_severe_band(self) -> None:
        assert compute_risk_tier(80.0) == RiskTier.SEVERE
        assert compute_risk_tier(100.0) == RiskTier.SEVERE

    def test_low_moderate_boundary(self) -> None:
        assert compute_risk_tier(39.9) == RiskTier.LOW
        assert compute_risk_tier(40.0) == RiskTier.MODERATE

    def test_moderate_high_boundary(self) -> None:
        assert compute_risk_tier(59.9) == RiskTier.MODERATE
        assert compute_risk_tier(60.0) == RiskTier.HIGH

    def test_high_severe_boundary(self) -> None:
        assert compute_risk_tier(79.9) == RiskTier.HIGH
        assert compute_risk_tier(80.0) == RiskTier.SEVERE
