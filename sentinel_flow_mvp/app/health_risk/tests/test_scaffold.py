"""
Tests for the health_risk domain module scaffold.

These tests prove the fundamental building blocks work:
  - RiskScore validation rejects out-of-range values.
  - RiskScore accepts valid values.
  - RiskScoringStrategy cannot be instantiated directly (ABC enforcement).
  - TransparentFormulaScorer can be instantiated and returns a valid RiskScore.
"""

from datetime import datetime, timezone

import pytest

from app.health_risk.domain.disease_category import DiseaseCategory
from app.health_risk.domain.risk_score import RiskScore
from app.health_risk.domain.scoring_strategy import RiskScoringStrategy
from app.health_risk.domain.transparent_formula_scorer import TransparentFormulaScorer


class TestRiskScoreValidation:
    """RiskScore must reject scores outside the 0.0-100.0 range."""

    def test_raises_value_error_when_score_is_150(self) -> None:
        """A score of 150.0 is above the maximum and must be rejected."""
        with pytest.raises(ValueError):
            RiskScore(
                pincode="682001",
                disease_category=DiseaseCategory.DENGUE,
                score=150.0,
                confidence="real_data",
                computed_at=datetime.now(timezone.utc),
                contributing_factors={"trend_score": 82.0},
            )

    def test_raises_value_error_when_score_is_negative_10(self) -> None:
        """A score of -10.0 is below the minimum and must be rejected."""
        with pytest.raises(ValueError):
            RiskScore(
                pincode="682001",
                disease_category=DiseaseCategory.DENGUE,
                score=-10.0,
                confidence="real_data",
                computed_at=datetime.now(timezone.utc),
                contributing_factors={"trend_score": 82.0},
            )

    def test_accepts_valid_score(self) -> None:
        """A score of 75.5 within the valid range should be accepted."""
        score = RiskScore(
            pincode="682001",
            disease_category=DiseaseCategory.DENGUE,
            score=75.5,
            confidence="real_data",
            computed_at=datetime.now(timezone.utc),
            contributing_factors={"trend_score": 82.0, "humidity_percent": 91.0},
        )
        assert score.score == 75.5
        assert score.confidence == "real_data"
        assert score.disease_category == DiseaseCategory.DENGUE


class TestRiskScoringStrategyContract:
    """The abstract base class must enforce the Strategy contract."""

    def test_cannot_instantiate_abstract_class_directly(self) -> None:
        """RiskScoringStrategy is abstract and should raise TypeError."""
        with pytest.raises(TypeError):
            RiskScoringStrategy()  # type: ignore[abstract]

    def test_transparent_formula_scorer_can_be_instantiated(self) -> None:
        """TransparentFormulaScorer is concrete and should work."""
        scorer = TransparentFormulaScorer()
        assert scorer is not None

    def test_transparent_formula_scorer_returns_valid_risk_score(self) -> None:
        """The placeholder scorer must return a RiskScore with fallback_neutral confidence."""
        scorer = TransparentFormulaScorer()
        result = scorer.calculate_risk(
            pincode="682001",
            disease_category=DiseaseCategory.LEPTOSPIROSIS,
            trend_score=None,
            humidity_percent=None,
            rain_mm=None,
        )
        assert isinstance(result, RiskScore)
        assert result.score == 50.0
        assert result.confidence == "fallback_neutral"
        assert result.disease_category == DiseaseCategory.LEPTOSPIROSIS
        assert result.pincode == "682001"
        assert result.contributing_factors is not None
