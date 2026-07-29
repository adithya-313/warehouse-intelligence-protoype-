"""
Tests for the real scoring formula and weather anomaly calculator.

These are pure-function tests — known inputs, known expected outputs,
no mocking needed. Every test proves a specific, documented behaviour:

Weather anomaly tests:
  - HIGH anomaly when humidity >80% AND rain >10mm
  - MODERATE anomaly when only one exceeds threshold
  - LOW anomaly when neither exceeds threshold
  - NEUTRAL (50.0) when any input is None

Scoring formula tests:
  - trend + weather → weighted average, confidence="real_data"
  - trend missing → weather only, confidence="fallback_neutral"
  - all missing → 50.0, confidence="fallback_neutral"
  - contributing_factors contains the exact raw inputs used
"""

from datetime import datetime, timezone

import pytest

from app.health_risk.domain.disease_category import DiseaseCategory
from app.health_risk.domain.risk_score import RiskScore
from app.health_risk.domain.transparent_formula_scorer import TransparentFormulaScorer
from app.health_risk.domain.weather_anomaly import calculate_weather_anomaly


# =========================================================================
# Weather anomaly tests
# =========================================================================


class TestWeatherAnomalyHigh:
    """Both humidity >80% and rain >10mm must return HIGH (90.0)."""

    def test_high_humidity_high_rain(self) -> None:
        """85% humidity and 15mm rain = both thresholds exceeded → 90.0."""
        assert calculate_weather_anomaly(85.0, 15.0) == 90.0

    def test_boundary_high(self) -> None:
        """Just above both thresholds (81% humidity, 11mm rain) → 90.0."""
        assert calculate_weather_anomaly(81.0, 11.0) == 90.0

    def test_extreme_values(self) -> None:
        """100% humidity and 100mm rain → still 90.0 (capped)."""
        assert calculate_weather_anomaly(100.0, 100.0) == 90.0


class TestWeatherAnomalyModerate:
    """Only one condition met returns MODERATE (60.0)."""

    def test_high_humidity_only(self) -> None:
        """Humidity=85% (>80%) but rain=5mm (<10mm) → 60.0."""
        assert calculate_weather_anomaly(85.0, 5.0) == 60.0

    def test_high_rain_only(self) -> None:
        """Rain=15mm (>10mm) but humidity=50% (<80%) → 60.0."""
        assert calculate_weather_anomaly(50.0, 15.0) == 60.0


class TestWeatherAnomalyLow:
    """Neither condition met returns LOW (20.0)."""

    def test_both_low(self) -> None:
        """Humidity=50% and rain=5mm → 20.0."""
        assert calculate_weather_anomaly(50.0, 5.0) == 20.0

    def test_barely_below_thresholds(self) -> None:
        """79% humidity and 9mm rain → 20.0."""
        assert calculate_weather_anomaly(79.0, 9.0) == 20.0

    def test_zero_values(self) -> None:
        """0% humidity and 0mm rain → 20.0."""
        assert calculate_weather_anomaly(0.0, 0.0) == 20.0


class TestWeatherAnomalyMissingData:
    """Missing inputs return NEUTRAL (50.0) — never crash."""

    def test_none_humidity(self) -> None:
        """humidity_percent=None → 50.0 regardless of rain."""
        assert calculate_weather_anomaly(None, 15.0) == 50.0

    def test_none_rain(self) -> None:
        """rain_mm=None → 50.0 regardless of humidity."""
        assert calculate_weather_anomaly(85.0, None) == 50.0

    def test_both_none(self) -> None:
        """Both None → 50.0."""
        assert calculate_weather_anomaly(None, None) == 50.0


# =========================================================================
# Scoring formula tests
# =========================================================================


class TestScoringFormulaRealData:
    """All data present → weighted average + confidence="real_data"."""

    def test_high_trend_high_weather(self) -> None:
        """
        trend=90 (high), humidity=85%/rain=15mm (weather_anomaly=90).
        Expected: (90 * 0.6) + (90 * 0.4) = 54 + 36 = 90.0
        """
        scorer = TransparentFormulaScorer()
        result = scorer.calculate_risk(
            pincode="682001",
            disease_category=DiseaseCategory.DENGUE,
            trend_score=90.0,
            humidity_percent=85.0,
            rain_mm=15.0,
        )

        expected = (90.0 * 0.6) + (90.0 * 0.4)
        assert result.score == expected
        assert result.confidence == "real_data"
        assert isinstance(result, RiskScore)

    def test_mid_trend_moderate_weather(self) -> None:
        """
        trend=50 (mid), humidity=50%/rain=5mm (weather_anomaly=20).
        Expected: (50 * 0.6) + (20 * 0.4) = 30 + 8 = 38.0
        """
        scorer = TransparentFormulaScorer()
        result = scorer.calculate_risk(
            pincode="682001",
            disease_category=DiseaseCategory.LEPTOSPIROSIS,
            trend_score=50.0,
            humidity_percent=50.0,
            rain_mm=5.0,
        )

        expected = (50.0 * 0.6) + (20.0 * 0.4)
        assert result.score == expected
        assert result.confidence == "real_data"

    def test_zero_trend_low_weather(self) -> None:
        """
        trend=0, humidity=0%/rain=0mm (weather_anomaly=20).
        Expected: (0 * 0.6) + (20 * 0.4) = 0 + 8 = 8.0
        """
        scorer = TransparentFormulaScorer()
        result = scorer.calculate_risk(
            pincode="682001",
            disease_category=DiseaseCategory.DENGUE,
            trend_score=0.0,
            humidity_percent=0.0,
            rain_mm=0.0,
        )

        expected = (0.0 * 0.6) + (20.0 * 0.4)
        assert result.score == expected
        assert result.confidence == "real_data"


class TestScoringFormulaFallbackNeutral:
    """Missing data → graceful degradation, confidence="fallback_neutral"."""

    def test_trend_none_uses_weather_only(self) -> None:
        """
        trend=None, humidity=85%/rain=15mm (weather_anomaly=90).
        No trend data → use weather alone → score=90.0.
        """
        scorer = TransparentFormulaScorer()
        result = scorer.calculate_risk(
            pincode="682001",
            disease_category=DiseaseCategory.DENGUE,
            trend_score=None,
            humidity_percent=85.0,
            rain_mm=15.0,
        )

        assert result.score == 90.0
        assert result.confidence == "fallback_neutral"

    def test_trend_none_moderate_weather(self) -> None:
        """
        trend=None, humidity=85%/rain=5mm (weather_anomaly=60).
        No trend → weather alone → score=60.0.
        """
        scorer = TransparentFormulaScorer()
        result = scorer.calculate_risk(
            pincode="682001",
            disease_category=DiseaseCategory.LEPTOSPIROSIS,
            trend_score=None,
            humidity_percent=85.0,
            rain_mm=5.0,
        )

        assert result.score == 60.0
        assert result.confidence == "fallback_neutral"

    def test_trend_none_weather_partial(self) -> None:
        """
        trend=None, humidity=None, rain=15mm (weather_anomaly=50.0 — neutral).
        When one weather input is None, weather_anomaly() returns 50.0.
        """
        scorer = TransparentFormulaScorer()
        result = scorer.calculate_risk(
            pincode="682001",
            disease_category=DiseaseCategory.VIRAL_FEVER,
            trend_score=None,
            humidity_percent=None,
            rain_mm=15.0,
        )

        assert result.score == 50.0
        assert result.confidence == "fallback_neutral"

    def test_all_none(self) -> None:
        """
        All inputs None → score=50.0, confidence="fallback_neutral".
        This must NOT crash — it is the baseline fallback when the
        entire data pipeline is down.
        """
        scorer = TransparentFormulaScorer()
        result = scorer.calculate_risk(
            pincode="682001",
            disease_category=DiseaseCategory.DENGUE,
            trend_score=None,
            humidity_percent=None,
            rain_mm=None,
        )

        assert result.score == 50.0
        assert result.confidence == "fallback_neutral"
        assert result.disease_category == DiseaseCategory.DENGUE
        assert result.pincode == "682001"


class TestScoringFormulaContributingFactors:
    """contributing_factors must contain every raw input used."""

    def test_all_inputs_present_in_factors(self) -> None:
        """
        When all inputs provided, contributing_factors must contain:
        trend_score, humidity_percent, rain_mm, and the calculated weather_anomaly.
        """
        scorer = TransparentFormulaScorer()
        result = scorer.calculate_risk(
            pincode="682001",
            disease_category=DiseaseCategory.DENGUE,
            trend_score=82.0,
            humidity_percent=91.0,
            rain_mm=12.0,
        )

        assert result.contributing_factors["trend_score"] == 82.0
        assert result.contributing_factors["humidity_percent"] == 91.0
        assert result.contributing_factors["rain_mm"] == 12.0
        # The calculated weather anomaly must also be in the receipt
        assert result.contributing_factors["weather_anomaly"] == 90.0

    def test_partial_inputs_in_factors(self) -> None:
        """
        When trend is None and weather is partial, contributing_factors
        must still contain the actual values passed (including None).
        """
        scorer = TransparentFormulaScorer()
        result = scorer.calculate_risk(
            pincode="682001",
            disease_category=DiseaseCategory.DENGUE,
            trend_score=None,
            humidity_percent=85.0,
            rain_mm=None,
        )

        assert result.contributing_factors["trend_score"] is None
        assert result.contributing_factors["humidity_percent"] == 85.0
        assert result.contributing_factors["rain_mm"] is None
        assert result.contributing_factors["weather_anomaly"] == 50.0

    def test_all_none_in_factors(self) -> None:
        """
        When everything is None, contributing_factors must show all None
        values and the neutral weather_anomaly.
        """
        scorer = TransparentFormulaScorer()
        result = scorer.calculate_risk(
            pincode="682001",
            disease_category=DiseaseCategory.DENGUE,
            trend_score=None,
            humidity_percent=None,
            rain_mm=None,
        )

        assert result.contributing_factors["trend_score"] is None
        assert result.contributing_factors["humidity_percent"] is None
        assert result.contributing_factors["rain_mm"] is None
        assert result.contributing_factors["weather_anomaly"] == 50.0
