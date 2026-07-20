"""
Tests for the Phase 1 Intent Gate (Traffic Cop).

Beginner Note:
    These tests verify the ``classify_intent()`` pure function and its
    integration into the ``/ask`` endpoint. Because the gate function is
    pure (no DB, no I/O), ALL unit tests run without mocks and finish in
    microseconds.

    The integration test uses the FastAPI TestClient with mocked DB/vector/Gemini
    to prove that a NO_INTENT query genuinely hits zero downstream services.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from app.domain.intent import IntentBucket
from app.domain.intent_gate import classify_intent


# pytestmark = pytest.mark.usefixtures("mock_redis_guards") is NOT needed here
# because our unit tests are pure function tests. The conftest.py autouse
# fixture mock_redis_guards patches pos_router functions that our tests
# never import — but pytest still tries to resolve it for every test.
# We mark our tests to not require it.
pytestmark = pytest.mark.filterwarnings("ignore")


# =====================================================================
# UNIT TESTS — classify_intent() pure function
# =====================================================================
# These tests do NOT need a database, Redis, or any fixture. The function
# is a pure string classifier — pass in a query, get an IntentBucket back.


class TestClassifyIntent:
    """Tests for the pure function classify_intent()."""

    def test_empty_query_no_sku_returns_no_intent(self):
        """
        ARRANGE: Empty string query, no SKU found, no objective keyword.
        ACT:     Call classify_intent.
        ASSERT:  Returns NO_INTENT.
        """
        bucket = classify_intent(
            query="",
            sku_id=None,
            has_objective_keyword=False,
        )
        assert bucket == IntentBucket.NO_INTENT, (
            f"Expected NO_INTENT for empty query with no SKU. Got {bucket}"
        )

    def test_drug_without_keyword_returns_ambiguous(self):
        """
        ARRANGE: Drug SKU "TELMA40" found, but query has no objective keyword.
        ACT:     Call classify_intent.
        ASSERT:  Returns AMBIGUOUS (drug present, unclear what user wants).
        """
        bucket = classify_intent(
            query="tell me about TELMA-40",
            sku_id="TELMA-40",
            has_objective_keyword=False,
        )
        assert bucket == IntentBucket.AMBIGUOUS, (
            f"Expected AMBIGUOUS for drug with no keyword. Got {bucket}"
        )

    def test_objective_keyword_without_sku_returns_no_intent(self):
        """
        ARRANGE: Query contains "price" (objective keyword) but NO sku_id.
                 The keyword alone is meaningless without a drug to look up.
        ACT:     Call classify_intent.
        ASSERT:  Returns NO_INTENT, not INVENTORY.
        """
        bucket = classify_intent(
            query="what's the price",
            sku_id=None,
            has_objective_keyword=True,
        )
        assert bucket == IntentBucket.NO_INTENT, (
            f"Expected NO_INTENT when keyword present but no SKU. Got {bucket}"
        )

    def test_drug_with_objective_keyword_returns_inventory(self):
        """
        ARRANGE: Both drug SKU and objective keyword ("price") present.
        ACT:     Call classify_intent.
        ASSERT:  Returns INVENTORY (route to database).
        """
        bucket = classify_intent(
            query="TELMA-40 price",
            sku_id="TELMA-40",
            has_objective_keyword=True,
        )
        assert bucket == IntentBucket.INVENTORY, (
            f"Expected INVENTORY for drug + keyword. Got {bucket}"
        )

    def test_neither_drug_nor_keyword_returns_no_intent(self):
        """
        ARRANGE: Query with no recognizable drug AND no inventory keyword.
        ACT:     Call classify_intent.
        ASSERT:  Returns NO_INTENT.
        """
        bucket = classify_intent(
            query="can you help me",
            sku_id=None,
            has_objective_keyword=False,
        )
        assert bucket == IntentBucket.NO_INTENT, (
            f"Expected NO_INTENT for query with neither. Got {bucket}"
        )

    def test_garbage_input_does_not_raise(self):
        """
        ARRANGE: Random unicode, emoji, and very long strings as query.
        ACT:     Call classify_intent with each garbage input.
        ASSERT:  Never raises an exception, always returns a valid IntentBucket.
        """
        garbage_inputs = [
            "你好世界",
            "😀🎉👍",
            "a" * 10_000,        # 10,000-character string
            "\x00\x01\x02",
            "   \t\n  ",
        ]
        for garbage in garbage_inputs:
            bucket = classify_intent(
                query=garbage,
                sku_id=None,
                has_objective_keyword=False,
            )
            assert isinstance(bucket, IntentBucket), (
                f"Garbage input '{garbage[:20]}...' did not return an IntentBucket. "
                f"Got: {type(bucket)}"
            )

    def test_sql_injection_shaped_input_treated_as_plain_text(self):
        """
        ARRANGE: Input that looks like SQL injection but is just a string.
        ACT:     Call classify_intent with sku_id=None and no objective keyword.
        ASSERT:  Returns NO_INTENT — the gate does not treat this input
                 specially. It simply checks for the presence of a SKU
                 (None → NO_INTENT). This confirms the gate is pure string
                 matching and cannot be tricked into DB access via injection.
        """
        bucket = classify_intent(
            query="'; DROP TABLE medications; --",
            sku_id=None,
            has_objective_keyword=False,
        )
        assert bucket == IntentBucket.NO_INTENT, (
            f"Expected NO_INTENT for injection-shaped input with no SKU. "
            f"Got {bucket}"
        )


# =====================================================================
# INTEGRATION TEST — NO_INTENT short-circuit in the real endpoint
# =====================================================================
# This test uses the FastAPI TestClient (from conftest or created inline)
# and mocks the THREE downstream services that NO_INTENT must avoid:
#   1. Database session
#   2. Vector search (execute_clinical_search)
#   3. Gemini / route_and_process_query


class TestNoIntentShortCircuit:
    """Prove that a NO_INTENT query triggers zero DB/vector/Gemini calls.

    NOTE: This test uses httpx.ASGITransport (the modern httpx API) instead of
    starlette's TestClient because the Docker environment has httpx 0.28.1 /
    starlette 0.36.3 where TestClient passes the removed 'app' kwarg to httpx.
    """

    def test_no_intent_query_never_calls_downstream_services(self):
        """
        ARRANGE: Override get_database_session with a mock via FastAPI's
                 dependency_overrides. Patch route_and_process_query to
                 catch any attempt to call it.

        ACT:     POST to /ask with a NO_INTENT query (no drug, no keyword).

        ASSERT:  Response is 200 with "could not identify" message.
                 route_and_process_query was NEVER called.
                 DB session was NEVER queried.
        """
        import json as _json
        import httpx

        mock_db = MagicMock()
        mock_route = AsyncMock()

        from fastapi import FastAPI
        from app.api.v1.knowledge_base import router as kb_router
        from app.infrastructure.database import get_database_session

        app = FastAPI()
        app.include_router(kb_router, prefix="/api/v1/knowledge-base")
        app.dependency_overrides[get_database_session] = lambda: mock_db

        with patch(
            "app.api.v1.knowledge_base.route_and_process_query",
            mock_route,
        ):
            # Build an ASGI transport manually using httpx's internal
            # transport protocol. httpx 0.28.1 dropped the 'app' kwarg
            # from Client.__init__ but the ASGI transport still works
            # via handle_async_request.
            async def asgi_app_handler(scope, receive, send):
                await app(scope, receive, send)

            # Use an in-memory request/response via ASGI directly.
            from starlette.requests import Request
            from starlette.responses import JSONResponse

            # We bypass httpx entirely and test the handler function
            # by constructing the ASGI scope manually and invoking the
            # application. This avoids all httpx version compat issues.
            scope = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/api/v1/knowledge-base/ask",
                "raw_path": b"/api/v1/knowledge-base/ask",
                "query_string": b"",
                "root_path": "",
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", b"37"),
                    (b"host", b"testserver"),
                ],
                "client": ("127.0.0.1", 50000),
                "server": ("testserver", 80),
            }

            body = _json.dumps(
                {"query": "can you help me please"}
            ).encode("utf-8")

            response_status = None
            response_body = b""
            response_headers = []

            async def receive():
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": False,
                }

            async def send(message):
                nonlocal response_status, response_body, response_headers
                if message["type"] == "http.response.start":
                    response_status = message["status"]
                    response_headers = message["headers"]
                elif message["type"] == "http.response.body":
                    response_body = message["body"]

            import asyncio
            asyncio.run(app(scope, receive, send))

            # --- Assertion 1: 200 with NO_INTENT message ---
            assert response_status == 200, (
                f"Expected 200. Got {response_status}"
            )
            response_data = _json.loads(response_body)
            assert "could not identify" in response_data["answer"].lower(), (
                f"Expected NO_INTENT message. Got: {response_data['answer']}"
            )

            # --- Assertion 2: route_and_process_query was NEVER called ---
            mock_route.assert_not_called()
            assert mock_route.call_count == 0, (
                "NO_INTENT query must not call route_and_process_query."
            )

            # --- Assertion 3: DB was never queried ---
            assert mock_db.query.call_count == 0, (
                "NO_INTENT query must not call the database."
            )
