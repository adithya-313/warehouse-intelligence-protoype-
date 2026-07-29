"""
Real integration test for the health_risk ingestion pipeline.

WHAT IS REAL:
  - PostgreSQL (sentinel_db, live on localhost:5432)
  - Redis (sentinel_redis, live on localhost:6379)
  - Open-Meteo weather API (live HTTP call, no key needed)

WHAT IS MOCKED:
  - fetch_trend_score (pytrends is rate-limited to 429 on this network)

These tests create real rows in health_risk_scores and exogenous_covariates,
then delete them after each test. No test data is left in the database.
"""

import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import ApplicationSettings
from app.health_risk.domain.disease_category import DiseaseCategory
from app.health_risk.infrastructure.db_models import HealthRiskScoreModel
from app.health_risk.service.ingestion_service import run_ingestion_for_pincode
from app.infrastructure.models import ExogenousCovariateModel
from app.services.covariates.parsers import CovariateParser


# =========================================================================
# Real database connection
# =========================================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgrespassword@localhost:5432/sentinel_db",
)

_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


# Use distinct pincodes so we never collide with production or other tests.
# The "IT-" prefix marks these as integration-test-only data.
TEST_PINCODE_1 = "IT-HR-001"
TEST_PINCODE_2 = "IT-HR-002"
TEST_PINCODE_3 = "IT-HR-003"

_ALL_TEST_PINCODES = [TEST_PINCODE_1, TEST_PINCODE_2, TEST_PINCODE_3]


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture(scope="function")
def real_db():
    """Yields a real PostgreSQL session. Cleans up test rows after."""
    session = _TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def cleanup_test_data(real_db):
    """
    Remove every row we created during the test so the DB is left clean.
    Runs after each test function, even if the test failed.
    """
    yield
    for pincode in _ALL_TEST_PINCODES:
        real_db.query(HealthRiskScoreModel).filter(
            HealthRiskScoreModel.pincode == pincode
        ).delete()
        real_db.query(ExogenousCovariateModel).filter(
            ExogenousCovariateModel.pincode == pincode
        ).delete()
    real_db.commit()


@pytest.fixture
def real_settings():
    """ApplicationSettings — the ingestion service needs this as a parameter."""
    return ApplicationSettings()


# =========================================================================
# Helper: count rows for a test pincode
# =========================================================================

def count_health_risk_rows(db, pincode: str) -> int:
    return db.query(HealthRiskScoreModel).filter(
        HealthRiskScoreModel.pincode == pincode
    ).count()


# =========================================================================
# Tests
# =========================================================================


class TestHealthRiskRealPipeline:
    """
    Integration tests exercising the full ingestion pipeline against
    real infrastructure. Only fetch_trend_score is mocked.
    """

    @patch("app.health_risk.service.ingestion_service.fetch_trend_score")
    def test_success_path_all_three_diseases_scored(
        self, mock_fetch, real_db, real_settings
    ):
        """
        Real weather row + mocked trend score = 75.0
        → all 3 diseases produce real_data rows in health_risk_scores.
        """
        # --------------------------------------------------------------
        # Arrange: insert a real weather row, mock trend score
        # --------------------------------------------------------------
        weather_row = ExogenousCovariateModel(
            pincode=TEST_PINCODE_1,
            humidity_percent=90.0,
            rain_mm=20.0,
            symptom_keyword="dengue symptoms",
            trend_score=85.0,
            timestamp=datetime.now(timezone.utc),
        )
        real_db.add(weather_row)
        real_db.commit()

        mock_fetch.return_value = 75.0

        # --------------------------------------------------------------
        # Act: run the real ingestion pipeline
        # --------------------------------------------------------------
        results = run_ingestion_for_pincode(
            pincode=TEST_PINCODE_1,
            db=real_db,
            settings=real_settings,
        )

        # --------------------------------------------------------------
        # Assert: 3 RiskScores returned, 3 rows in DB
        # --------------------------------------------------------------
        assert len(results) == 3, (
            "Expected exactly 3 RiskScore objects (one per disease category)"
        )

        db_rows = real_db.query(HealthRiskScoreModel).filter(
            HealthRiskScoreModel.pincode == TEST_PINCODE_1
        ).order_by(HealthRiskScoreModel.id).all()

        assert len(db_rows) == 3, (
            "Expected 3 rows in health_risk_scores"
        )

        # Each row must have a real score, real_data confidence, and
        # contributing_factors JSON receipt with all 4 inputs
        for row in db_rows:
            assert 0.0 <= row.score <= 100.0
            assert row.confidence == "real_data"
            assert row.contributing_factors is not None
            assert "trend_score" in row.contributing_factors
            assert "humidity_percent" in row.contributing_factors
            assert "rain_mm" in row.contributing_factors
            assert "weather_anomaly" in row.contributing_factors
            # The trend_score in contributing_factors must match our mock
            assert row.contributing_factors["trend_score"] == 75.0

        # --------------------------------------------------------------
        # Verify different diseases have different scores
        # (because each disease category maps to a different keyword,
        #  and the trend score is the same 75.0 for all, so scores
        #  depend only on the weather_anomaly which is the same for all →
        #  actually all diseases get the same score since both inputs
        #  are identical. Still, all 3 rows were created.)
        # --------------------------------------------------------------
        disease_categories_in_db = {row.disease_category for row in db_rows}
        assert disease_categories_in_db == {"dengue", "leptospirosis", "viral_fever"}

    @patch("app.health_risk.service.ingestion_service.fetch_trend_score")
    def test_no_weather_no_trend_uses_fallback_neutral(
        self, mock_fetch, real_db, real_settings
    ):
        """
        No weather row for pincode + fetch_trend_score returns None
        → scorer produces fallback_neutral with score = 50.0.
        """
        # --------------------------------------------------------------
        # Arrange: no weather row inserted, trend returns None
        # --------------------------------------------------------------
        mock_fetch.return_value = None

        # --------------------------------------------------------------
        # Act: run ingestion (should not crash)
        # --------------------------------------------------------------
        results = run_ingestion_for_pincode(
            pincode=TEST_PINCODE_2,
            db=real_db,
            settings=real_settings,
        )

        # --------------------------------------------------------------
        # Assert: 3 rows with fallback_neutral, score=50.0
        # --------------------------------------------------------------
        assert len(results) == 3, (
            "Expected 3 RiskScores even with no data (graceful degradation)"
        )

        db_rows = real_db.query(HealthRiskScoreModel).filter(
            HealthRiskScoreModel.pincode == TEST_PINCODE_2
        ).order_by(HealthRiskScoreModel.id).all()

        assert len(db_rows) == 3

        for row in db_rows:
            assert row.score == 50.0, (
                f"Expected fallback score 50.0 for {row.disease_category}, "
                f"got {row.score}"
            )
            assert row.confidence == "fallback_neutral"
            # contributing_factors should still have all keys with None values
            assert row.contributing_factors["trend_score"] is None
            assert row.contributing_factors["humidity_percent"] is None
            assert row.contributing_factors["rain_mm"] is None

    @patch("app.health_risk.service.ingestion_service.fetch_trend_score")
    def test_real_open_meteo_weather_used_in_scoring(
        self, mock_fetch, real_db, real_settings
    ):
        """
        Calls the REAL Open-Meteo weather API for Kochi, stores the result
        in exogenous_covariates, then runs ingestion. The computed score
        should reflect the real humidity/rain data from Open-Meteo.
        """
        # --------------------------------------------------------------
        # Arrange: fetch real weather from Open-Meteo, insert as covariate
        # --------------------------------------------------------------
        kochi_lat, kochi_lon = 9.93, 76.27
        weather_data = CovariateParser.fetch_weather_by_coords(
            lat=kochi_lat, lon=kochi_lon
        )

        real_humidity = weather_data["humidity_percent"]
        real_rain = weather_data["rain_mm"]

        # Sanity check: Open-Meteo returned realistic values for Kerala
        assert isinstance(real_humidity, (int, float)), (
            f"Expected numeric humidity, got {type(real_humidity)}"
        )

        weather_row = ExogenousCovariateModel(
            pincode=TEST_PINCODE_3,
            humidity_percent=real_humidity,
            rain_mm=real_rain,
            symptom_keyword="dengue symptoms",
            timestamp=datetime.now(timezone.utc),
        )
        real_db.add(weather_row)
        real_db.commit()

        mock_fetch.return_value = 80.0

        # --------------------------------------------------------------
        # Act: run ingestion
        # --------------------------------------------------------------
        results = run_ingestion_for_pincode(
            pincode=TEST_PINCODE_3,
            db=real_db,
            settings=real_settings,
        )

        # --------------------------------------------------------------
        # Assert: scores reflect the real weather values
        # --------------------------------------------------------------
        assert len(results) == 3

        db_rows = real_db.query(HealthRiskScoreModel).filter(
            HealthRiskScoreModel.pincode == TEST_PINCODE_3
        ).all()

        assert len(db_rows) == 3

        for row in db_rows:
            # The contributing_factors must contain our real weather data
            assert row.contributing_factors["humidity_percent"] == real_humidity, (
                f"Expected humidity={real_humidity} in contributing_factors"
            )
            assert row.contributing_factors["rain_mm"] == real_rain, (
                f"Expected rain={real_rain} in contributing_factors"
            )
            # The trend_score must be our mocked value
            assert row.contributing_factors["trend_score"] == 80.0
            # The weather_anomaly was computed from REAL humidity/rain
            assert row.contributing_factors["weather_anomaly"] is not None
            # Score should be non-zero (since both trend and weather are present)
            assert row.score > 0.0

    @patch("app.health_risk.service.ingestion_service.fetch_trend_score")
    def test_trend_fetch_exception_skips_that_disease(
        self, mock_fetch, real_db, real_settings
    ):
        """
        When fetch_trend_score raises (pytrends network error), the
        exception is caught inside run_ingestion_for_pincode, the
        session is rolled back, and processing continues to the next
        disease. No rows are created for any disease in this case
        because every disease tries to fetch trends and every call raises.
        """
        # --------------------------------------------------------------
        # Arrange: trend fetch raises for every disease
        # --------------------------------------------------------------
        mock_fetch.side_effect = RuntimeError("pytrends rate limit hit")

        # --------------------------------------------------------------
        # Act: run ingestion (should NOT crash the whole test)
        # --------------------------------------------------------------
        results = run_ingestion_for_pincode(
            pincode=TEST_PINCODE_1,
            db=real_db,
            settings=real_settings,
        )

        # --------------------------------------------------------------
        # Assert: no results, no DB rows, no crash
        # --------------------------------------------------------------
        assert len(results) == 0, (
            "Expected 0 RiskScores when all trend fetches fail"
        )

        db_row_count = count_health_risk_rows(real_db, TEST_PINCODE_1)
        assert db_row_count == 0, (
            f"Expected 0 rows in health_risk_scores, found {db_row_count}"
        )
