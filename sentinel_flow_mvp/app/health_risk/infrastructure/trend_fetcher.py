"""
Fetches real Google Trends search interest for symptom keywords.

WHY THIS EXISTS SEPARATELY FROM THE EXISTING CovariateParser.fetch_trends_by_city:
The existing parser in app/services/covariates/parsers.py returns simulated data
(hardcoded scores for "Bengaluru", "Mumbai", "Delhi"). This module replaces THAT
simulation with REAL data from pytrends, but lives in the health_risk bounded
context so we can ship it independently without touching the old code path.

DESIGN DECISIONS:
1. Returns None instead of crashing — the 6-hour background ingestion job
   should NEVER fail completely just because Google Trends was unreachable.
   A None means "no real data this cycle" and the caller picks the fallback.
2. Uses the existing AegisLiteCircuitBreaker so repeated failures don't hammer
   Google's servers — after 3 failures the circuit opens and we return None
   without even attempting the HTTP call.
3. Uses the same tenacity retry pattern as CovariateParser (3 attempts,
   exponential backoff) so transient network errors self-heal.
4. Caches in Redis with 6-hour TTL so repeated calls for the same pincode
   and keyword return instantly without hitting Google.
"""

import json
import logging
from typing import Optional

import redis
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.circuit_breaker import AegisLiteCircuitBreaker, CircuitStateEnum
from app.core.config import get_application_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Circuit breaker configuration for trend fetching.
# We use a SEPARATE instance from the ML circuit breaker because trend
# fetching and ML inference have different failure characteristics and
# should not share the same circuit state.
# ---------------------------------------------------------------------------
# 3 failures in a row → open the circuit for 60 seconds
_trend_circuit_breaker = AegisLiteCircuitBreaker(
    failure_threshold=3,
    recovery_timeout=60,
    success_threshold=2,
)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _call_pytrends(keyword: str) -> Optional[float]:
    """
    Makes the actual HTTP call to Google Trends.

    WHY SEPARATE FROM fetch_trend_score:
    The tenacity retry decorator wraps this inner function only, not the
    caching logic or the circuit breaker check. This way, retries happen
    ONLY when we have decided to actually call Google, not for cache hits
    or circuit-break fast-fails.
    """
    from pytrends.request import TrendReq

    # Connect to Google Trends with a 10-second total timeout
    # (2 seconds to connect, 8 seconds to read the response)
    pytrends = TrendReq(
        hl="en-US",
        tz=360,
        timeout=(2, 8),
    )

    # Build the payload for the keyword — look at the last 3 months
    pytrends.build_payload(kw_list=[keyword], timeframe="today 3-m")

    # Get the interest-over-time DataFrame (values are 0 to 100)
    interest_df = pytrends.interest_over_time()

    # If the DataFrame is empty, Google had no data for this keyword
    if interest_df is None or interest_df.empty:
        logger.info(f"No trend data returned for keyword '{keyword}'.")
        return None

    # The most recent row has the latest interest value
    latest_score = float(interest_df[keyword].iloc[-1])
    logger.info(f"Trend score for '{keyword}': {latest_score}")
    return latest_score


def fetch_trend_score(pincode: str, symptom_keyword: str) -> Optional[float]:
    """
    Fetch real Google Trends search interest for a symptom keyword.

    This is the PUBLIC entry point. It handles:
      1. Redis cache check (return cached value if fresh).
      2. Circuit breaker check (return None fast if circuit is open).
      3. pytrends call with retry (via _call_pytrends).
      4. Cache the result in Redis for 6 hours.
      5. Update circuit breaker state on success/failure.

    WHY RETURN None INSTEAD OF CRASHING:
    This function is called by a 6-hour background ingestion job. If Google
    Trends is temporarily down, we want the job to complete successfully with
    a "no data" signal rather than failing the entire cycle. The caller
    (TransparentFormulaScorer) will use fallback_neutral confidence when
    trend_score is None, so the system keeps working without real data.
    """
    settings = get_application_settings()

    # ------------------------------------------------------------------
    # Step 1: Check Redis cache — avoid calling Google unnecessarily
    # ------------------------------------------------------------------
    cache_key = f"trend_cache:{pincode}:{symptom_keyword}"
    redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

    try:
        cached_value = redis_client.get(cache_key)
        if cached_value is not None:
            logger.info(
                f"Cache HIT for trend '{symptom_keyword}' at pincode {pincode}: {cached_value}"
            )
            return float(cached_value)
    except Exception as cache_error:
        # If Redis is down, log and continue — we still want to try Google
        logger.warning(f"Redis cache unavailable, proceeding without cache: {cache_error}")

    # ------------------------------------------------------------------
    # Step 2: Circuit breaker check — fail fast if Google is down
    # ------------------------------------------------------------------
    # If the circuit is OPEN, we check whether enough recovery time has
    # passed. If not, return None without making any network call.
    if _trend_circuit_breaker.current_state == CircuitStateEnum.OPEN:
        if not _trend_circuit_breaker._should_attempt_recovery():
            logger.warning(
                f"Circuit breaker OPEN for trend fetch. "
                f"Skipping '{symptom_keyword}' at pincode {pincode}."
            )
            return None
        else:
            # Enough time has passed — move to HALF_OPEN for a test call
            _trend_circuit_breaker.current_state = CircuitStateEnum.HALF_OPEN
            logger.info("Circuit breaker half-open: attempting trend fetch recovery.")

    # ------------------------------------------------------------------
    # Step 3: Call Google Trends with retry
    # ------------------------------------------------------------------
    try:
        trend_score = _call_pytrends(symptom_keyword)
        _trend_circuit_breaker._on_success()

        # Cache the result (even if None — we cache None to avoid retrying
        # keywords Google has no data for)
        try:
            if trend_score is not None:
                redis_client.setex(cache_key, 21600, str(trend_score))
        except Exception as cache_error:
            logger.warning(f"Failed to write trend cache: {cache_error}")

        return trend_score

    except Exception as error:
        logger.error(
            f"Failed to fetch trend for '{symptom_keyword}' at pincode {pincode}: {error}"
        )
        _trend_circuit_breaker._on_failure()
        return None
