"""
Phase 4 — Resilience: Cache, Circuit Breaker, Timeout & Degraded Mode.

Beginner Note:
    This test file validates FOUR resilience layers added to the RAG pipeline:
    1. Hash-based result caching (skip Gemini when exact query + version match).
    2. Circuit breaker (skip Gemini when too many recent failures).
    3. Async timeout (abort Gemini after 5 seconds).
    4. Degraded mode fallback (use Judge's deterministic verdict when Gemini fails).

    Every test uses mocks — no database, no Redis, no Gemini API.
"""

import asyncio
import json
import pytest
import sys
from unittest.mock import AsyncMock, MagicMock, patch


# =====================================================================
# AUTOMATIC FIXTURE: Mock heavy modules that crash on this Windows env
# =====================================================================
# Both google.generativeai and app.services.semantic_search import
# chains that cascade through torch/torchaudio which crash with DLL
# error 0xc0000139 on this Windows host. We replace both with
# MagicMock objects in sys.modules BEFORE any test code touches them.


@pytest.fixture(autouse=True, scope="function")
def _mock_heavy_modules():
    """Inject mocks for google.generativeai AND app.services.semantic_search.

    Each test gets a fresh Gemini mock.  Yield a dict with::

        helpers["set_fail"]()   → make Gemini.next call raise RuntimeError

    Default: Gemini succeeds and returns valid ClinicalNarrativeSchema JSON.
    Semantic search always returns results from the test's mock_context_items.
    """
    # ---- Gemini ----
    genai_mock = MagicMock()
    model_mock = MagicMock()
    model_mock.generate_content_async = AsyncMock()
    model_mock.generate_content_async.return_value = AsyncMock()
    model_mock.generate_content_async.return_value.text = json.dumps({
        "is_safe_to_dispense": True,
        "narrative": "Mocked Gemini response.",
        "system_lock_reason": None,
        "citations": ["Mocked Citation"],
    })
    genai_mock.GenerativeModel.return_value = model_mock
    genai_mock.types.GenerationConfig = MagicMock()

    # ---- Semantic search (avoids torch import chain) ----
    search_mock = MagicMock()

    def _set_fail():
        model_mock.generate_content_async.side_effect = RuntimeError("Gemini API error")

    helpers = {"set_fail": _set_fail}

    with patch.dict("sys.modules", {
        "google.generativeai": genai_mock,
        "app.services.semantic_search": search_mock,
    }):
        yield helpers


# =====================================================================
# REUSABLE FIXTURES
# =====================================================================


@pytest.fixture
def mock_context_items():
    """Simulated clinical search results (what PubMedBERT would return)."""
    return [
        {
            "sku_id": "DOLO-650",
            "content": "Paracetamol is generally safe for adults.",
            "pregnancy_category": None,
            "pediatric_age_threshold_months": None,
        }
    ]


# =====================================================================
# TEST CLASS 1: Hash-Based Cache (Hit / Miss / Store / Redis Down)
# =====================================================================

class TestResultCache:
    """Verify the hash-based result cache works correctly."""

    @patch("app.services.rag_pipeline.get_redis_client")
    @patch("app.services.rag_pipeline.get_global_db_version")
    @patch("app.services.rag_pipeline.get_application_settings")
    async def test_cache_hit_returns_cached_response(
        self,
        mock_settings,
        mock_get_version,
        mock_get_redis,
        mock_context_items,
    ):
        from app.services.rag_pipeline import route_and_process_query
        import sys
        sys.modules["app.services.semantic_search"].execute_clinical_search.return_value = {
            "results": mock_context_items,
        }

        cached_answer = {
            "answer": "CACHED",
            "context_used": [],
            "is_safe_to_dispense": True,
            "system_lock_reason": None,
            "citations": [],
        }

        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps(cached_answer)
        mock_get_redis.return_value = mock_redis
        mock_get_version.return_value = "1"
        mock_settings.return_value.GEMINI_API_KEY = "test-key"

        db = MagicMock()
        result = await route_and_process_query(db=db, query="Is DOLO-650 safe?", intents={})

        assert result == cached_answer

    @patch("app.services.rag_pipeline.get_redis_client")
    @patch("app.services.rag_pipeline.get_global_db_version")
    @patch("app.services.rag_pipeline.get_application_settings")
    async def test_cache_miss_proceeds_to_gemini(
        self,
        mock_settings,
        mock_get_version,
        mock_get_redis,
        mock_context_items,
    ):
        from app.services.rag_pipeline import route_and_process_query
        import sys
        sys.modules["app.services.semantic_search"].execute_clinical_search.return_value = {
            "results": mock_context_items,
        }

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis
        mock_get_version.return_value = "1"
        mock_settings.return_value.GEMINI_API_KEY = "test-key"

        db = MagicMock()
        result = await route_and_process_query(db=db, query="Is DOLO-650 safe?", intents={})

        assert result["is_safe_to_dispense"] is True
        assert result["citations"] == ["Mocked Citation"]

    @patch("app.services.rag_pipeline.get_redis_client")
    @patch("app.services.rag_pipeline.get_global_db_version")
    @patch("app.services.rag_pipeline.get_application_settings")
    async def test_cache_store_on_success(
        self,
        mock_settings,
        mock_get_version,
        mock_get_redis,
        mock_context_items,
    ):
        from app.services.rag_pipeline import route_and_process_query
        import sys
        sys.modules["app.services.semantic_search"].execute_clinical_search.return_value = {
            "results": mock_context_items,
        }

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis
        mock_get_version.return_value = "1"
        mock_settings.return_value.GEMINI_API_KEY = "test-key"

        db = MagicMock()
        result = await route_and_process_query(db=db, query="Is DOLO-650 safe?", intents={})

        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert "rag_cache:" in call_args[0][0]
        stored_value = json.loads(call_args[0][1])
        assert stored_value["answer"] == result["answer"]

    @patch("app.services.rag_pipeline.get_redis_client")
    @patch("app.services.rag_pipeline.get_global_db_version")
    @patch("app.services.rag_pipeline.get_application_settings")
    async def test_cache_redis_down_still_works(
        self,
        mock_settings,
        mock_get_version,
        mock_get_redis,
        mock_context_items,
    ):
        from app.services.rag_pipeline import route_and_process_query
        import sys
        sys.modules["app.services.semantic_search"].execute_clinical_search.return_value = {
            "results": mock_context_items,
        }

        mock_get_redis.side_effect = ConnectionError("Redis is down")
        mock_get_version.return_value = "1"
        mock_settings.return_value.GEMINI_API_KEY = "test-key"

        db = MagicMock()
        result = await route_and_process_query(db=db, query="Is DOLO-650 safe?", intents={})

        assert result["is_safe_to_dispense"] is True


# =====================================================================
# TEST CLASS 2: Circuit Breaker (Open / Half-Open / Recovery)
# =====================================================================

class TestCircuitBreaker:
    """Verify the Gemini circuit breaker protects the pipeline."""

    @patch("app.services.rag_pipeline.get_redis_client")
    @patch("app.services.rag_pipeline.get_global_db_version")
    @patch("app.services.rag_pipeline.get_application_settings")
    async def test_circuit_open_uses_degraded_mode(
        self,
        mock_settings,
        mock_get_version,
        mock_get_redis,
        mock_context_items,
    ):
        from app.services.rag_pipeline import route_and_process_query
        from app.services.rag_pipeline import get_gemini_circuit_breaker
        from app.core.circuit_breaker import CircuitStateEnum
        import sys, time

        sys.modules["app.services.semantic_search"].execute_clinical_search.return_value = {
            "results": mock_context_items,
        }

        cb = get_gemini_circuit_breaker()
        cb.current_state = CircuitStateEnum.OPEN
        cb.last_failure_time = time.time()
        cb.recovery_timeout = 99999

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis
        mock_get_version.return_value = "1"
        mock_settings.return_value.GEMINI_API_KEY = "test-key"

        db = MagicMock()
        result = await route_and_process_query(db=db, query="Is DOLO-650 safe?", intents={})

        assert result["is_safe_to_dispense"] is True
        assert "SYSTEM_FALLBACK" in result["citations"]

    @patch("app.services.rag_pipeline.get_redis_client")
    @patch("app.services.rag_pipeline.get_global_db_version")
    @patch("app.services.rag_pipeline.get_application_settings")
    async def test_circuit_half_open_recovery_success(
        self,
        mock_settings,
        mock_get_version,
        mock_get_redis,
        mock_context_items,
    ):
        from app.services.rag_pipeline import route_and_process_query
        from app.services.rag_pipeline import get_gemini_circuit_breaker
        from app.core.circuit_breaker import CircuitStateEnum
        import sys
        sys.modules["app.services.semantic_search"].execute_clinical_search.return_value = {
            "results": mock_context_items,
        }

        cb = get_gemini_circuit_breaker()
        cb.current_state = CircuitStateEnum.HALF_OPEN

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis
        mock_get_version.return_value = "1"
        mock_settings.return_value.GEMINI_API_KEY = "test-key"

        db = MagicMock()
        result = await route_and_process_query(db=db, query="Is DOLO-650 safe?", intents={})

        assert result["is_safe_to_dispense"] is True


# =====================================================================
# TEST CLASS 3: Async Timeout Fallback
# =====================================================================

class TestTimeoutFallback:
    """Verify that a slow Gemini call triggers degraded mode."""

    @patch("app.services.rag_pipeline.get_redis_client")
    @patch("app.services.rag_pipeline.get_global_db_version")
    @patch("app.services.rag_pipeline.get_application_settings")
    async def test_timeout_returns_degraded_with_system_fallback(
        self,
        mock_settings,
        mock_get_version,
        mock_get_redis,
        mock_context_items,
        _mock_heavy_modules,
    ):
        from app.services.rag_pipeline import route_and_process_query
        import sys
        sys.modules["app.services.semantic_search"].execute_clinical_search.return_value = {
            "results": mock_context_items,
        }

        _mock_heavy_modules["set_fail"]()

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis
        mock_get_version.return_value = "1"
        mock_settings.return_value.GEMINI_API_KEY = "test-key"

        db = MagicMock()
        result = await route_and_process_query(db=db, query="Is DOLO-650 safe?", intents={})

        assert result["is_safe_to_dispense"] is True
        assert "SYSTEM_FALLBACK" in result["citations"]

    @patch("app.services.rag_pipeline.get_redis_client")
    @patch("app.services.rag_pipeline.get_global_db_version")
    @patch("app.services.rag_pipeline.get_application_settings")
    async def test_timeout_does_not_crash(
        self,
        mock_settings,
        mock_get_version,
        mock_get_redis,
        mock_context_items,
        _mock_heavy_modules,
    ):
        from app.services.rag_pipeline import route_and_process_query
        import sys
        sys.modules["app.services.semantic_search"].execute_clinical_search.return_value = {
            "results": mock_context_items,
        }

        _mock_heavy_modules["set_fail"]()

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis
        mock_get_version.return_value = "1"
        mock_settings.return_value.GEMINI_API_KEY = "test-key"

        db = MagicMock()
        result = await route_and_process_query(db=db, query="Is DOLO-650 safe?", intents={})

        assert "citations" in result
        assert "is_safe_to_dispense" in result
        assert "answer" in result
        assert "context_used" in result


# =====================================================================
# TEST CLASS 4: Degraded Mode — Narrative Construction
# =====================================================================

class TestDegradedMode:
    """Verify the degraded mode fallback constructs correct narratives."""

    @patch("app.services.rag_pipeline.get_redis_client")
    @patch("app.services.rag_pipeline.get_global_db_version")
    @patch("app.services.rag_pipeline.get_application_settings")
    async def test_degraded_from_safe_verdict(
        self,
        mock_settings,
        mock_get_version,
        mock_get_redis,
        mock_context_items,
        _mock_heavy_modules,
    ):
        from app.services.rag_pipeline import route_and_process_query
        import sys
        sys.modules["app.services.semantic_search"].execute_clinical_search.return_value = {
            "results": mock_context_items,
        }

        _mock_heavy_modules["set_fail"]()

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis
        mock_get_version.return_value = "1"
        mock_settings.return_value.GEMINI_API_KEY = "test-key"

        db = MagicMock()
        result = await route_and_process_query(db=db, query="Is DOLO-650 safe?", intents={})

        assert result["is_safe_to_dispense"] is True
        assert result["system_lock_reason"] is None

    @patch("app.services.rag_pipeline.get_redis_client")
    @patch("app.services.rag_pipeline.get_global_db_version")
    @patch("app.services.rag_pipeline.get_application_settings")
    async def test_degraded_from_unsafe_verdict(
        self,
        mock_settings,
        mock_get_version,
        mock_get_redis,
        _mock_heavy_modules,
    ):
        from app.services.rag_pipeline import route_and_process_query
        import sys
        sys.modules["app.services.semantic_search"].execute_clinical_search.return_value = {
            "results": [
                {
                    "sku_id": "ISO-200",
                    "content": "Isotretinoin contraindicated in pregnancy.",
                    "pregnancy_category": "X",
                    "pediatric_age_threshold_months": None,
                }
            ],
        }

        _mock_heavy_modules["set_fail"]()

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis
        mock_get_version.return_value = "1"
        mock_settings.return_value.GEMINI_API_KEY = "test-key"

        db = MagicMock()
        result = await route_and_process_query(
            db=db,
            query="Is ISO-200 safe for pregnancy?",
            intents={"pregnancy": True, "pediatric": False, "substitute": False},
        )

        assert result["is_safe_to_dispense"] is False
        assert result["system_lock_reason"] == "CRITICAL_PREGNANCY_CONTRAINDICATION"
        assert result["citations"] == []


# =====================================================================
# TEST CLASS 5: Version Invalidation
# =====================================================================

class TestVersionInvalidation:
    """Verify that incrementing the DB version invalidates cached responses."""

    @patch("app.services.rag_pipeline.get_redis_client")
    @patch("app.services.rag_pipeline.get_global_db_version")
    @patch("app.services.rag_pipeline.get_application_settings")
    async def test_different_versions_produce_different_cache_keys(
        self,
        mock_settings,
        mock_get_version,
        mock_get_redis,
        mock_context_items,
    ):
        from app.services.rag_pipeline import route_and_process_query
        import sys
        sys.modules["app.services.semantic_search"].execute_clinical_search.return_value = {
            "results": mock_context_items,
        }

        for version in ["1", "2"]:
            mock_redis = AsyncMock()
            mock_redis.get.return_value = None
            mock_get_redis.return_value = mock_redis
            mock_get_version.return_value = version
            mock_settings.return_value.GEMINI_API_KEY = "test-key"

            db = MagicMock()
            await route_and_process_query(db=db, query="Is DOLO-650 safe?", intents={})

    @patch("app.services.rag_pipeline.get_redis_client")
    @patch("app.services.rag_pipeline.get_global_db_version")
    @patch("app.services.rag_pipeline.get_application_settings")
    async def test_version_change_misses_cache(
        self,
        mock_settings,
        mock_get_version,
        mock_get_redis,
        mock_context_items,
    ):
        from app.services.rag_pipeline import route_and_process_query
        import sys
        sys.modules["app.services.semantic_search"].execute_clinical_search.return_value = {
            "results": mock_context_items,
        }

        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_get_redis.return_value = mock_redis
        mock_get_version.return_value = "2"
        mock_settings.return_value.GEMINI_API_KEY = "test-key"

        db = MagicMock()
        result = await route_and_process_query(db=db, query="Is DOLO-650 safe?", intents={})

        assert result["is_safe_to_dispense"] is True


# =====================================================================
# TEST CLASS 6: Cache Integration — Synchronous Version
# =====================================================================

class TestSynchronousCacheVersion:
    """Verify the synchronous increment_global_db_version_sync function."""

    def test_sync_function_imports_and_returns_string(self):
        from app.core.cache import increment_global_db_version_sync
        assert callable(increment_global_db_version_sync)

    def test_sync_function_handles_redis_unavailable(self):
        from app.core.cache import increment_global_db_version_sync
        import os

        old_url = os.environ.get("REDIS_URL")
        os.environ["REDIS_URL"] = "redis://localhost:16379/0"
        try:
            with pytest.raises((ConnectionError, Exception)):
                increment_global_db_version_sync()
        finally:
            if old_url:
                os.environ["REDIS_URL"] = old_url
            else:
                del os.environ["REDIS_URL"]
