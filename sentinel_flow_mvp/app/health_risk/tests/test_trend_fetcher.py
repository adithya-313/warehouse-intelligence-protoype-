"""
Tests for the Google Trends fetcher.

These tests prove:
  - pytrends success → returns a float 0-100
  - pytrends failure → returns None, does not crash
  - Circuit breaker trips → returns None fast without calling pytrends
  - Redis cache hit → returns cached value without calling pytrends

All external calls (pytrends, Redis) are mocked — no real network in tests.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.health_risk.infrastructure.trend_fetcher import fetch_trend_score


class TestTrendFetcherSuccess:
    """When pytrends returns data, fetch_trend_score must return a valid float."""

    @patch("app.health_risk.infrastructure.trend_fetcher._call_pytrends")
    @patch("app.health_risk.infrastructure.trend_fetcher.redis.Redis.from_url")
    def test_returns_float_when_pytrends_succeeds(
        self, mock_redis_from_url: MagicMock, mock_call_pytrends: MagicMock
    ) -> None:
        """Given a successful pytrends call, we must get a float score back."""
        # Arrange: pytrends returns a score, Redis returns nothing (cache miss)
        mock_call_pytrends.return_value = 82.0
        mock_redis_instance = MagicMock()
        mock_redis_instance.get.return_value = None  # Cache miss
        mock_redis_from_url.return_value = mock_redis_instance

        # Act
        result = fetch_trend_score(pincode="682001", symptom_keyword="dengue symptoms")

        # Assert
        assert result is not None
        assert isinstance(result, float)
        assert 0.0 <= result <= 100.0

    @patch("app.health_risk.infrastructure.trend_fetcher._call_pytrends")
    @patch("app.health_risk.infrastructure.trend_fetcher.redis.Redis.from_url")
    def test_returns_float_at_boundaries(
        self, mock_redis_from_url: MagicMock, mock_call_pytrends: MagicMock
    ) -> None:
        """Scores of 0.0 and 100.0 are valid and must be accepted."""
        mock_call_pytrends.return_value = 0.0
        mock_redis_instance = MagicMock()
        mock_redis_instance.get.return_value = None
        mock_redis_from_url.return_value = mock_redis_instance

        result = fetch_trend_score(pincode="682001", symptom_keyword="no interest")

        assert result == 0.0
        assert isinstance(result, float)


class TestTrendFetcherFailure:
    """When pytrends fails, fetch_trend_score must return None, never crash."""

    @patch("app.health_risk.infrastructure.trend_fetcher._call_pytrends")
    @patch("app.health_risk.infrastructure.trend_fetcher.redis.Redis.from_url")
    def test_returns_none_when_pytrends_times_out(
        self, mock_redis_from_url: MagicMock, mock_call_pytrends: MagicMock
    ) -> None:
        """A timeout from pytrends must result in None, not an exception."""
        # Arrange: pytrends raises a timeout
        mock_call_pytrends.side_effect = TimeoutError("Google Trends timed out")
        mock_redis_instance = MagicMock()
        mock_redis_instance.get.return_value = None
        mock_redis_from_url.return_value = mock_redis_instance

        # Act — must NOT raise
        result = fetch_trend_score(pincode="682001", symptom_keyword="dengue symptoms")

        # Assert
        assert result is None

    @patch("app.health_risk.infrastructure.trend_fetcher._call_pytrends")
    @patch("app.health_risk.infrastructure.trend_fetcher.redis.Redis.from_url")
    def test_returns_none_when_pytrends_returns_empty(
        self, mock_redis_from_url: MagicMock, mock_call_pytrends: MagicMock
    ) -> None:
        """An empty response from pytrends (no data for keyword) must return None."""
        mock_call_pytrends.return_value = None
        mock_redis_instance = MagicMock()
        mock_redis_instance.get.return_value = None
        mock_redis_from_url.return_value = mock_redis_instance

        result = fetch_trend_score(pincode="682001", symptom_keyword="rare symptom")

        assert result is None


class TestTrendFetcherCircuitBreaker:
    """When the circuit breaker is open, returns None without calling pytrends."""

    @patch("app.health_risk.infrastructure.trend_fetcher._trend_circuit_breaker")
    @patch("app.health_risk.infrastructure.trend_fetcher._call_pytrends")
    @patch("app.health_risk.infrastructure.trend_fetcher.redis.Redis.from_url")
    def test_returns_none_without_calling_pytrends_when_circuit_open(
        self,
        mock_redis_from_url: MagicMock,
        mock_call_pytrends: MagicMock,
        mock_circuit_breaker: MagicMock,
    ) -> None:
        """
        When the circuit breaker state is OPEN and recovery timeout hasn't
        elapsed, we must return None immediately without calling pytrends.
        """
        # Arrange: circuit breaker says it's OPEN and not ready to recover
        from app.core.circuit_breaker import CircuitStateEnum

        mock_circuit_breaker.current_state = CircuitStateEnum.OPEN
        mock_circuit_breaker._should_attempt_recovery.return_value = False
        mock_redis_instance = MagicMock()
        mock_redis_instance.get.return_value = None
        mock_redis_from_url.return_value = mock_redis_instance

        # Act
        result = fetch_trend_score(pincode="682001", symptom_keyword="dengue symptoms")

        # Assert: pytrends was NEVER called because circuit is open
        mock_call_pytrends.assert_not_called()
        assert result is None


class TestTrendFetcherCache:
    """When Redis has a cached value, returns it without calling pytrends."""

    @patch("app.health_risk.infrastructure.trend_fetcher._call_pytrends")
    @patch("app.health_risk.infrastructure.trend_fetcher.redis.Redis.from_url")
    def test_uses_cached_value_without_calling_pytrends(
        self, mock_redis_from_url: MagicMock, mock_call_pytrends: MagicMock
    ) -> None:
        """
        Given a valid cached value in Redis, we return it immediately
        and never make the pytrends HTTP call.
        """
        # Arrange: Redis has a cached value, pytrends should NOT be called
        mock_redis_instance = MagicMock()
        mock_redis_instance.get.return_value = "91.5"  # Cache hit
        mock_redis_from_url.return_value = mock_redis_instance

        # Act
        result = fetch_trend_score(pincode="682001", symptom_keyword="dengue symptoms")

        # Assert: cached value returned, pytrends not called
        mock_call_pytrends.assert_not_called()
        assert result == 91.5
        assert isinstance(result, float)

    @patch("app.health_risk.infrastructure.trend_fetcher._call_pytrends")
    @patch("app.health_risk.infrastructure.trend_fetcher.redis.Redis.from_url")
    def test_cache_miss_calls_pytrends(
        self, mock_redis_from_url: MagicMock, mock_call_pytrends: MagicMock
    ) -> None:
        """
        When Redis has no cached value (cache miss), we proceed to call
        pytrends to get fresh data.
        """
        # Arrange: Redis cache miss, pytrends returns a value
        mock_redis_instance = MagicMock()
        mock_redis_instance.get.return_value = None  # Cache miss
        mock_redis_from_url.return_value = mock_redis_instance
        mock_call_pytrends.return_value = 45.0

        # Act
        result = fetch_trend_score(pincode="682001", symptom_keyword="dengue symptoms")

        # Assert: pytrends was called and we got the score back
        mock_call_pytrends.assert_called_once_with("dengue symptoms")
        assert result == 45.0
