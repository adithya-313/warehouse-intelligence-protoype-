"""
Tests for the health_risk ingestion orchestrator.

These tests verify:
  - All 3 diseases are scored and saved when everything works.
  - A failure in ONE disease does not block the other two.
  - The feature flag is NOT checked inside the ingestion function
    (it is checked at the caller level in the Celery task/API route).

We mock EVERYTHING external:
  - fetch_trend_score (Google Trends call)
  - db.query chain (database query for weather data)
  - db.add + db.commit (saving scores)

No real network or database connections are made.
"""

from unittest.mock import MagicMock, patch

from app.core.config import ApplicationSettings
from app.health_risk.domain.disease_category import DiseaseCategory
from app.health_risk.domain.risk_score import RiskScore
from app.health_risk.infrastructure.db_models import HealthRiskScoreModel
from app.health_risk.service.ingestion_service import run_ingestion_for_pincode


# =========================================================================
# Shared test data
# =========================================================================

_TEST_PINCODE = "682001"

# Expected scores when trend=90 for all 3 diseases + weather_anomaly=90
# Formula: (trend * 0.6) + (weather_anomaly * 0.4)
# DENGUE: 90*0.6 + 90*0.4 = 54 + 36 = 90.0  ✓
# LEPTOSPIROSIS: 75*0.6 + 90*0.4 = 45 + 36 = 81.0  ✓
# VIRAL_FEVER: 60*0.6 + 90*0.4 = 36 + 36 = 72.0  ✓

_TREND_SCORES: dict[DiseaseCategory, float] = {
    DiseaseCategory.DENGUE: 90.0,
    DiseaseCategory.LEPTOSPIROSIS: 75.0,
    DiseaseCategory.VIRAL_FEVER: 60.0,
}


def _make_mock_db(weather_row_exists: bool = True) -> MagicMock:
    """
    Build a mock SQLAlchemy session that returns a fake weather row
    (or None if weather_row_exists=False).
    """
    mock_db = MagicMock()

    if weather_row_exists:
        # Simulate an ExogenousCovariateModel row with weather data
        mock_weather_row = MagicMock()
        mock_weather_row.humidity_percent = 85.0
        mock_weather_row.rain_mm = 15.0
        query_result = mock_weather_row
    else:
        # Simulate no data for this pincode
        query_result = None

    # Configure the query chain: db.query(...).filter(...).order_by(...).first()
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = query_result

    return mock_db


def _make_settings() -> ApplicationSettings:
    """Create a default ApplicationSettings instance for tests."""
    return ApplicationSettings()


# =========================================================================
# Success case
# =========================================================================


class TestIngestionSuccess:
    """All 3 diseases score and save when nothing fails."""

    @patch("app.health_risk.service.ingestion_service.fetch_trend_score")
    def test_all_three_diseases_are_scored_and_saved(
        self,
        mock_fetch_trend_score: MagicMock,
    ) -> None:
        """
        Given a working trend fetcher and weather data in the DB,
        run_ingestion_for_pincode must return 3 RiskScores (one per disease)
        and save 3 rows to the database.
        """
        # Arrange: trend fetcher returns a score based on the keyword
        def trend_side_effect(pincode: str, symptom_keyword: str) -> float | None:
            # Map keyword back to the expected score
            keyword_to_score = {
                "dengue symptoms": 90.0,
                "leptospirosis symptoms": 75.0,
                "viral fever treatments": 60.0,
            }
            return keyword_to_score.get(symptom_keyword, None)

        mock_fetch_trend_score.side_effect = trend_side_effect
        mock_db = _make_mock_db(weather_row_exists=True)
        settings = _make_settings()

        # Act
        results = run_ingestion_for_pincode(
            pincode=_TEST_PINCODE,
            db=mock_db,
            settings=settings,
        )

        # Assert: 3 RiskScores returned, one per disease
        assert len(results) == 3
        assert all(isinstance(r, RiskScore) for r in results)

        # Verify each disease's score matches the expected weighted formula
        for risk_score in results:
            expected_score = (
                _TREND_SCORES[risk_score.disease_category] * 0.6 + 90.0 * 0.4
            )
            assert risk_score.score == expected_score, (
                f"Expected {expected_score} for {risk_score.disease_category.value}, "
                f"got {risk_score.score}"
            )
            assert risk_score.confidence == "real_data"
            assert risk_score.pincode == _TEST_PINCODE

        # Verify 3 rows were saved to the database
        assert mock_db.add.call_count == 3
        assert mock_db.commit.call_count == 3

        # Verify each saved row is a HealthRiskScoreModel with correct data
        for call_args in mock_db.add.call_args_list:
            saved_row = call_args[0][0]
            assert isinstance(saved_row, HealthRiskScoreModel)
            assert saved_row.pincode == _TEST_PINCODE
            assert saved_row.score >= 0.0
            assert saved_row.confidence == "real_data"

    @patch("app.health_risk.service.ingestion_service.fetch_trend_score")
    def test_no_weather_row_still_scores_all_diseases(
        self,
        mock_fetch_trend_score: MagicMock,
    ) -> None:
        """
        When no weather row exists in the DB for this pincode, the scorer
        receives None for humidity/rain and uses fallback_neutral. All 3
        diseases must still be scored (no crash).
        """
        mock_fetch_trend_score.return_value = 50.0
        mock_db = _make_mock_db(weather_row_exists=False)
        settings = _make_settings()

        results = run_ingestion_for_pincode(
            pincode=_TEST_PINCODE,
            db=mock_db,
            settings=settings,
        )

        assert len(results) == 3
        # No weather data → weather_anomaly=50 (neutral)
        # trend=50 → (50*0.6 + 50*0.4) = 50.0
        for risk_score in results:
            assert risk_score.score == 50.0
            assert risk_score.confidence == "real_data"
        assert mock_db.add.call_count == 3
        assert mock_db.commit.call_count == 3


# =========================================================================
# Failure isolation
# =========================================================================


class TestIngestionFailureIsolation:
    """A single disease failure must not block the other diseases."""

    @patch("app.health_risk.service.ingestion_service.fetch_trend_score")
    def test_one_disease_failure_does_not_block_others(
        self,
        mock_fetch_trend_score: MagicMock,
    ) -> None:
        """
        When fetch_trend_score raises an exception for leptospirosis (the
        middle disease in iteration order), the other two diseases (dengue
        and viral_fever) must still produce valid RiskScores.

        Expected call order (based on DiseaseCategory definition order):
          1. DENGUE — succeeds
          2. LEPTOSPIROSIS — raises, caught, logged
          3. VIRAL_FEVER — succeeds

        Result: 2 RiskScores returned, 2 rows saved.
        """
        # Arrange: make the trend fetcher raise for leptospirosis keyword
        call_count = 0

        def trend_side_effect(pincode: str, symptom_keyword: str) -> float | None:
            nonlocal call_count
            call_count += 1
            # Second call (index 1, 0-indexed) is leptospirosis
            if call_count == 2:
                raise RuntimeError(
                    "Google Trends timed out for leptospirosis symptoms"
                )
            # First call (dengue) and third call (viral_fever) succeed
            return 50.0

        mock_fetch_trend_score.side_effect = trend_side_effect
        mock_db = _make_mock_db(weather_row_exists=True)
        settings = _make_settings()

        # Act
        results = run_ingestion_for_pincode(
            pincode=_TEST_PINCODE,
            db=mock_db,
            settings=settings,
        )

        # Assert: only 2 RiskScores (dengue + viral_fever), leptospirosis failed
        assert len(results) == 2, (
            f"Expected 2 results (leptospirosis should have failed), got {len(results)}"
        )

        # The failing disease should NOT appear in results
        failed_disease = DiseaseCategory.LEPTOSPIROSIS
        recovered_categories = [r.disease_category for r in results]
        assert failed_disease not in recovered_categories, (
            f"Leptospirosis should NOT be in results, but got: {recovered_categories}"
        )

        # Both successful diseases should have valid scores
        for risk_score in results:
            assert isinstance(risk_score.score, float)
            assert 0.0 <= risk_score.score <= 100.0

        # Only 2 rows were committed (leptospirosis was never added)
        assert mock_db.add.call_count == 2
        assert mock_db.commit.call_count == 2


# =========================================================================
# Feature flag independence
# =========================================================================


class TestIngestionFeatureFlagIndependence:
    """run_ingestion_for_pincode must NOT check the feature flag itself."""

    @patch("app.health_risk.service.ingestion_service.fetch_trend_score")
    def test_no_feature_flag_check_inside_ingestion(
        self,
        mock_fetch_trend_score: MagicMock,
    ) -> None:
        """
        The ingestion function must NOT check the feature flag itself
        (that is the caller's responsibility). We prove this behaviourally:
        with HEALTH_RISK_ENABLED=False (the default), the function still
        produces all 3 scores — proving it does not check the flag.
        """
        mock_fetch_trend_score.return_value = 50.0
        mock_db = _make_mock_db(weather_row_exists=True)
        settings = _make_settings()  # HEALTH_RISK_ENABLED defaults to False

        results = run_ingestion_for_pincode(
            pincode=_TEST_PINCODE,
            db=mock_db,
            settings=settings,
        )

        assert len(results) == 3, (
            "run_ingestion_for_pincode must produce 3 scores even when "
            "settings.HEALTH_RISK_ENABLED is False — the flag check is "
            "the caller's responsibility."
        )
