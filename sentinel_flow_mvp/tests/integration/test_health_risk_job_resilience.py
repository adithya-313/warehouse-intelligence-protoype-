"""
Job-level resilience test for the health_risk ingestion pipeline.

PROVES: If pytrends starts failing repeatedly during a real multi-pincode
ingestion run (simulating the actual 6-hour job processing many pharmacies
in sequence), the whole job keeps going without crashing. Only individual
diseases within the affected window get fallback_neutral scores. After the
circuit breaker recovers, later pincodes get real_data again.

WHAT IS REAL:
  - PostgreSQL (sentinel_db, live on localhost:5432)
  - SQLAlchemy sessions and commits

WHAT IS MOCKED:
  - _call_pytrends (the underlying HTTP call to Google Trends)

ENV OVERRIDE:
  - REDIS_URL set to localhost:6379 (Docker hostname "redis" is not
    resolvable from the Windows host, causing 3-5s timeouts per call)

CIRCUIT BREAKER BEHAVIOR TESTED:
  - CLOSED -> 3 failures -> OPEN
  - OPEN -> fast-fail None (no http call attempted)
  - OPEN -> recovery_timeout elapsed -> HALF_OPEN -> success -> CLOSED
"""

import os
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.circuit_breaker import CircuitStateEnum
from app.core.config import ApplicationSettings
from app.health_risk.infrastructure.db_models import HealthRiskScoreModel
from app.health_risk.infrastructure.trend_fetcher import _trend_circuit_breaker
from app.health_risk.service.ingestion_service import run_ingestion_for_pincode
from app.infrastructure.models import ExogenousCovariateModel

# =========================================================================
# Real database connection
# =========================================================================

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgrespassword@localhost:5432/sentinel_db",
)

_engine = create_engine(DATABASE_URL, pool_pre_ping=True)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

# ---------------------------------------------------------------------------
# Test pincodes -- the "IT-HR-RES-" prefix ("RES" for "resilience") marks
# these as integration-test-only and distinct from the pipeline tests
# (IT-HR-00X) so cleanup scopes don't overlap.
# ---------------------------------------------------------------------------
TEST_PINCODES = [
    "IT-HR-RES-01",
    "IT-HR-RES-02",
    "IT-HR-RES-03",
    "IT-HR-RES-04",
    "IT-HR-RES-05",
]


# =========================================================================
# Fixtures
# =========================================================================


@pytest.fixture(scope="function")
def real_db():
    """Yields a real PostgreSQL session. Rolls back / closes on teardown."""
    session = _TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def cleanup_test_data(real_db):
    """
    Removes every row we created during the test so the DB is left clean.
    Runs after each test function, even if the test itself fails.
    """
    yield
    for pincode in TEST_PINCODES:
        real_db.query(HealthRiskScoreModel).filter(
            HealthRiskScoreModel.pincode == pincode
        ).delete()
        real_db.query(ExogenousCovariateModel).filter(
            ExogenousCovariateModel.pincode == pincode
        ).delete()
    real_db.commit()


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    """
    Resets the module-level trend circuit breaker to CLOSED before and
    after each test. This guarantees test isolation even if a previous
    test left the breaker in OPEN or HALF_OPEN state.
    """
    _trend_circuit_breaker.current_state = CircuitStateEnum.CLOSED
    _trend_circuit_breaker.failure_count = 0
    _trend_circuit_breaker.success_count = 0
    _trend_circuit_breaker.last_failure_time = None
    yield
    _trend_circuit_breaker.current_state = CircuitStateEnum.CLOSED
    _trend_circuit_breaker.failure_count = 0
    _trend_circuit_breaker.success_count = 0
    _trend_circuit_breaker.last_failure_time = None


@pytest.fixture
def real_settings():
    """ApplicationSettings instance for the ingestion service."""
    return ApplicationSettings()


@pytest.fixture
def seed_weather(real_db):
    """
    Inserts a moderate-weather row for every test pincode so the scorer
    always has real humidity/rain data (humidity=50, rain=5 -- neither
    threshold exceeded, so weather_anomaly=0). This makes the score
    purely trend-driven, isolating what we're testing: the trend fetcher
    and its circuit breaker.
    """
    for pincode in TEST_PINCODES:
        row = ExogenousCovariateModel(
            pincode=pincode,
            humidity_percent=50.0,
            rain_mm=5.0,
            symptom_keyword="dengue symptoms",
            timestamp=datetime.now(timezone.utc),
        )
        real_db.add(row)
    real_db.commit()


# =========================================================================
# Helper
# =========================================================================


def _count_db_rows(db, pincode: str) -> int:
    """Count health_risk_scores rows for a given pincode."""
    return db.query(HealthRiskScoreModel).filter(
        HealthRiskScoreModel.pincode == pincode
    ).count()


# =========================================================================
# Tests
# =========================================================================


@pytest.mark.integration
class TestHealthRiskJobResilience:
    """
    Simulate a "mini ingestion job": a loop that calls
    run_ingestion_for_pincode() for 5 different test pincodes in sequence,
    while pytrends fails partway through. Prove the job survives.
    """

    @patch("app.health_risk.infrastructure.trend_fetcher._call_pytrends")
    def test_job_survives_sustained_pytrends_failure(
        self,
        mock_call_pytrends,
        real_db,
        real_settings,
        seed_weather,
    ):
        """
        Full scenario:
          1. _call_pytrends raises for the first 3 disease calls
             (pincode 1's 3 diseases) -> CB opens
          2. Pincodes 2-3 hit the OPEN CB -> fast-fail None -> fallback_neutral
          3. We force CB recovery by rewinding last_failure_time
          4. Pincodes 4-5 get real_data again once pytrends is healthy

        Assertions:
          a. CB state trace: CLOSED -> OPEN -> (stay OPEN) -> HALF_OPEN -> CLOSED
          b. All 5 pincodes produce exactly 3 RiskScores each (= 15 total)
          c. No exception propagates (proved by reaching these assertions)
          d. Pincodes 1-3 have fallback_neutral, 4-5 have real_data
        """

        # ------------------------------------------------------------------
        # Arrange: set REDIS_URL to localhost (Docker hostname "redis" is
        # not resolvable from Windows host — causes 3-5s timeouts per call)
        # and mock _call_pytrends to fail 3 times, then succeed
        # ------------------------------------------------------------------

        # Override REDIS_URL before any fetch_trend_score call reads it
        os.environ["REDIS_URL"] = "redis://localhost:6379"

        # First 3 calls raise (3 diseases in pincode 1 -> CB opens).
        # Subsequent calls return 75.0 (pincodes 4-5 after CB recovers).
        failure = Exception("TooManyRequestsError")
        mock_call_pytrends.side_effect = [failure] * 3 + [75.0] * 100

        # ------------------------------------------------------------------
        # Act Step 1: process pincode 1 (all 3 disease calls fail)
        # ------------------------------------------------------------------

        cb_state_start = _trend_circuit_breaker.current_state

        results_p1 = run_ingestion_for_pincode(
            pincode=TEST_PINCODES[0],
            db=real_db,
            settings=real_settings,
        )

        cb_state_after_p1 = _trend_circuit_breaker.current_state
        cb_failures_after_p1 = _trend_circuit_breaker.failure_count

        # ------------------------------------------------------------------
        # Act Step 2: process pincodes 2 and 3 (CB is OPEN -> fast-fail)
        # ------------------------------------------------------------------

        results_p2 = run_ingestion_for_pincode(
            pincode=TEST_PINCODES[1],
            db=real_db,
            settings=real_settings,
        )

        results_p3 = run_ingestion_for_pincode(
            pincode=TEST_PINCODES[2],
            db=real_db,
            settings=real_settings,
        )

        cb_state_after_p3 = _trend_circuit_breaker.current_state

        # ------------------------------------------------------------------
        # Act Step 3: force CB recovery by rewinding last_failure_time
        # ------------------------------------------------------------------
        #
        # _should_attempt_recovery() checks:
        #     time.time() - self.last_failure_time >= self.recovery_timeout
        #
        # We set last_failure_time to (recovery_timeout + 1) seconds ago,
        # so the next fetch call sees the timeout as elapsed.
        # ------------------------------------------------------------------

        _trend_circuit_breaker.last_failure_time = (
            time.time() - _trend_circuit_breaker.recovery_timeout - 1
        )

        # State hasn't changed yet (no call made since we set the time)
        cb_state_after_time_travel = _trend_circuit_breaker.current_state

        # ------------------------------------------------------------------
        # Act Step 4: process pincode 4 (first call after recovery)
        # ------------------------------------------------------------------
        #
        # Disease 1: OPEN -> _should_attempt_recovery()=True -> HALF_OPEN
        #            -> _call_pytrends succeeds -> _on_success()
        #            -> HALF_OPEN (success_count=1)
        # Disease 2: HALF_OPEN (skip OPEN check) -> _call_pytrends succeeds
        #            -> _on_success() -> CLOSED (success_count=2 >= 2)
        # Disease 3: CLOSED -> normal flow
        # ------------------------------------------------------------------

        results_p4 = run_ingestion_for_pincode(
            pincode=TEST_PINCODES[3],
            db=real_db,
            settings=real_settings,
        )

        cb_state_after_p4 = _trend_circuit_breaker.current_state

        # ------------------------------------------------------------------
        # Act Step 5: process pincode 5 (fully recovered circuit)
        # ------------------------------------------------------------------

        results_p5 = run_ingestion_for_pincode(
            pincode=TEST_PINCODES[4],
            db=real_db,
            settings=real_settings,
        )

        cb_state_after_p5 = _trend_circuit_breaker.current_state

        # ==================================================================
        # Assertions
        # ==================================================================

        # ----- a. Circuit breaker state machine trace ---------------------

        assert cb_state_start == CircuitStateEnum.CLOSED, (
            f"Expected initial state CLOSED, got {cb_state_start}"
        )

        # 3 consecutive failures (from pincode 1's 3 diseases) >= threshold 3 -> OPEN
        assert cb_state_after_p1 == CircuitStateEnum.OPEN, (
            f"Expected CB state OPEN after 3 failures, got {cb_state_after_p1}"
        )
        assert cb_failures_after_p1 == 3, (
            f"Expected failure_count=3 after 3 failures, got {cb_failures_after_p1}"
        )

        # CB stays OPEN while no success occurs (p2 and p3 don't call pytrends)
        assert cb_state_after_p3 == CircuitStateEnum.OPEN, (
            f"Expected CB state still OPEN after pincode 3, got {cb_state_after_p3}"
        )

        # After time travel, CB is still OPEN (the transition to HALF_OPEN
        # happens inside the next fetch_trend_score call, not before)
        assert cb_state_after_time_travel == CircuitStateEnum.OPEN, (
            f"Expected CB still OPEN after time travel, got {cb_state_after_time_travel}"
        )

        # After pincode 4, the CB should be CLOSED:
        #   Disease 1: HALF_OPEN after recovery check -> success -> HALF_OPEN (count=1)
        #   Disease 2: HALF_OPEN -> success -> CLOSED (count=2 >= success_threshold=2)
        #   Disease 3: CLOSED -> normal
        assert cb_state_after_p4 == CircuitStateEnum.CLOSED, (
            f"Expected CB state CLOSED after pincode 4 successes, "
            f"got {cb_state_after_p4}"
        )

        # Pincode 5: circuit stayed CLOSED throughout
        assert cb_state_after_p5 == CircuitStateEnum.CLOSED, (
            f"Expected CB state CLOSED after pincode 5, got {cb_state_after_p5}"
        )

        # ----- b. ALL 5 pincodes produce exactly 3 RiskScores each --------

        all_results = results_p1 + results_p2 + results_p3 + results_p4 + results_p5
        assert len(all_results) == 15, (
            f"Expected 15 total RiskScores (5 pincodes x 3 diseases), "
            f"got {len(all_results)}"
        )

        # Verify each pincode individually
        for idx, results in enumerate(
            [results_p1, results_p2, results_p3, results_p4, results_p5]
        ):
            assert len(results) == 3, (
                f"Pincode {TEST_PINCODES[idx]} returned {len(results)} "
                f"RiskScores, expected 3"
            )

        # Also verify DB rows match (each row was committed)
        for pincode in TEST_PINCODES:
            assert _count_db_rows(real_db, pincode) == 3, (
                f"Expected 3 DB rows for pincode {pincode}"
            )

        # ----- c. No exception propagates --------------------------------
        # This assertion is trivially true -- if any exception had propagated
        # out of run_ingestion_for_pincode, we would never have reached
        # this line. Stated explicitly for documentation.
        assert True, (
            "Job completed without propagating any exception "
            "(all 5 run_ingestion_for_pincode calls returned normally)"
        )

        # ----- d. Confidence matches expected phase -----------------------

        # Pincode 1: _call_pytrends raised -> trend_score=None -> fallback_neutral
        for rs in results_p1:
            assert rs.confidence == "fallback_neutral", (
                f"Expected fallback_neutral for pincode 1 disease "
                f"'{rs.disease_category}', got {rs.confidence}"
            )

        # Pincode 2-3: CB was OPEN -> fetch_trend_score returned None
        # (fast-fail, never called _call_pytrends) -> fallback_neutral
        for rs in results_p2 + results_p3:
            assert rs.confidence == "fallback_neutral", (
                f"Expected fallback_neutral for pincode during OPEN circuit, "
                f"got {rs.confidence}"
            )

        # Pincode 4-5: CB recovered -> _call_pytrends succeeded -> real_data
        for rs in results_p4 + results_p5:
            assert rs.confidence == "real_data", (
                f"Expected real_data for pincode after CB recovery, "
                f"got {rs.confidence}"
            )
