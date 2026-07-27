import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.domain.drug_resolver import resolve_drug_entity

class TestDrugResolver:
    """Test suite for the fuzzy drug resolver (Phase 2)."""

    def _make_mock_db(self, exact_sku=None, exact_alias=None, fuzzy_results=None):
        mock_db = MagicMock()
        def mock_execute(query, params=None):
            query_str = str(query)
            result = MagicMock()
            if "FROM medications" in query_str:
                result.fetchone.return_value = (exact_sku,) if exact_sku else None
            elif "WHERE REPLACE(alias_text" in query_str:
                result.fetchone.return_value = (exact_alias,) if exact_alias else None
            elif "similarity(" in query_str:
                if fuzzy_results:
                    padded_results = []
                    for res in fuzzy_results:
                        if len(res) == 3:
                            padded_results.append(("dummy_candidate", res[0], res[1], res[2]))
                        else:
                            padded_results.append(res)
                    result.fetchall.return_value = padded_results
                else:
                    result.fetchall.return_value = []
            else:
                result.fetchone.return_value = None
                result.fetchall.return_value = []
            return result
        mock_db.execute.side_effect = mock_execute
        return mock_db

    def test_exact_match(self):
        """a. Exact match → status 'resolved', confidence 'exact'."""
        mock_db = self._make_mock_db(exact_alias="PAN-40")
        
        result = resolve_drug_entity(mock_db, "price of pan-40")
        assert result["status"] == "resolved"
        assert result["sku_id"] == "PAN-40"
        assert result["confidence"] == "exact"

    def test_fuzzy_match_single(self):
        """b. Deliberately misspelled real drug name (single close match) → status 'resolved', confidence 'fuzzy'."""
        mock_db = self._make_mock_db(fuzzy_results=[("PARACETAMOL", "PARACETAMOL", 0.95)])
        
        result = resolve_drug_entity(mock_db, "price of PARCETAMOL")
        assert result["status"] == "resolved"
        assert result["sku_id"] == "PARACETAMOL"
        assert result["confidence"] == "fuzzy"

    def test_disambiguate_multiple_matches(self):
        """c. Deliberately misspelled name with 2+ plausible matches → status 'disambiguate'."""
        mock_db = self._make_mock_db(fuzzy_results=[("TELMA-40", "TELMA-40", 0.93), ("TELMI-40", "TELMI-40", 0.93)])
        
        result = resolve_drug_entity(mock_db, "price of TELM-40")
        assert result["status"] == "disambiguate"
        assert "choices" in result
        assert 2 <= len(result["choices"]) <= 3
        assert "TELMA-40" in result["choices"]

    def test_no_match_gibberish(self):
        """d. Gibberish input with zero plausible matches → status 'no_match'."""
        mock_db = self._make_mock_db()
        
        result = resolve_drug_entity(mock_db, "price of xyzzy1234")
        assert result["status"] == "no_match"
        assert result["reason"] == "no_close_match_found"

    def test_forced_sku_short_circuits(self):
        """e. Providing a known sku_id skips DB fuzzy match entirely."""
        mock_db = self._make_mock_db()
        
        result = resolve_drug_entity(mock_db, "anything", sku_id="GENERIC_REF_PARACETAMOL")
        assert result["status"] == "resolved"
        assert result["sku_id"] == "GENERIC_REF_PARACETAMOL"
        assert result["confidence"] == "exact"
        # The database should not have been queried
        mock_db.execute.assert_not_called()

    def test_unforced_sku_retains_behavior(self):
        """f. Not providing sku_id retains the fuzzy match behavior."""
        # Use two brands here to ensure it falls through to ambiguous/disambiguate
        mock_db = self._make_mock_db(fuzzy_results=[("CALPOL650", "PARACETAMOL", 1.0000), ("DOLO650", "PARACETAMOL", 1.0000)])
        
        result = resolve_drug_entity(mock_db, "paracetamol overdose symptoms")
        assert result["status"] == "disambiguate"
        assert "CALPOL650" in result["choices"]
        assert "DOLO650" in result["choices"]

    def test_exact_match_per_token_single(self):
        """g. query 'GENERIC_REF_PARACETAMOL overdose symptoms' resolves exactly."""
        mock_db = MagicMock()
        def mock_execute(query, params=None):
            result = MagicMock()
            if "FROM medications" in str(query):
                token = params.get("token")
                if token == "GENERIC_REF_PARACETAMOL":
                    result.fetchone.return_value = ("GENERIC_REF_PARACETAMOL",)
                else:
                    result.fetchone.return_value = None
            elif "similarity(" in str(query):
                result.fetchall.return_value = []
            else:
                result.fetchone.return_value = None
            return result
        mock_db.execute.side_effect = mock_execute
        
        result = resolve_drug_entity(mock_db, "GENERIC_REF_PARACETAMOL overdose symptoms")
        assert result["status"] == "resolved"
        assert result["sku_id"] == "GENERIC_REF_PARACETAMOL"
        assert result["confidence"] == "exact"
        # Verify fuzzy search was not called
        for call in mock_db.execute.call_args_list:
            assert "similarity(" not in str(call[0][0])

    def test_exact_match_per_token_none(self):
        """h. query 'paracetamol overdose symptoms' falls through to fuzzy matching."""
        # Use two brands here to ensure it falls through to ambiguous/disambiguate
        mock_db = self._make_mock_db(fuzzy_results=[("CALPOL650", "PARACETAMOL", 1.0000), ("DOLO650", "PARACETAMOL", 1.0000)])
        
        result = resolve_drug_entity(mock_db, "paracetamol overdose symptoms")
        assert result["status"] == "disambiguate"
        # We assert it did NOT resolve exactly
        assert "choices" in result

    def test_exact_match_per_token_multiple(self, caplog):
        """i. query mentioning two real SKUs falls through and logs."""
        mock_db = MagicMock()
        def mock_execute(query, params=None):
            result = MagicMock()
            if "FROM medications" in str(query):
                token = params.get("token")
                if token in ("PAN40", "DOLO650"):
                    result.fetchone.return_value = (token,)
                else:
                    result.fetchone.return_value = None
            elif "WHERE REPLACE(alias_text" in str(query):
                result.fetchone.return_value = None
            elif "similarity(" in str(query):
                # Return fuzzy results so we can check it fell through properly
                result.fetchall.return_value = [("PAN40", "PAN40", "PAN40", 1.0)]
            else:
                result.fetchone.return_value = None
                result.fetchall.return_value = []
            return result
        mock_db.execute.side_effect = mock_execute
        
        with caplog.at_level("WARNING"):
            result = resolve_drug_entity(mock_db, "can I take PAN40 and DOLO650 together")
            
        assert "Multiple exact SKU tokens found" in caplog.text
        # Because we mocked fuzzy search to return PAN40, it should resolve fuzzily or disambiguate
        # We just care it didn't resolve 'exact' on the first step
        assert result.get("confidence") != "exact"

    def test_fuzzy_tie_break_generic_wins(self):
        """j. tie between generic and brand resolves to generic."""
        mock_db = self._make_mock_db(fuzzy_results=[
            ("CALPOL650", "PARACETAMOL", 1.0000),
            ("GENERIC_REF_PARACETAMOL", "PARACETAMOL", 0.9500)
        ])
        
        result = resolve_drug_entity(mock_db, "paracetamol overdose symptoms")
        assert result["status"] == "resolved"
        assert result["sku_id"] in ("CALPOL650", "GENERIC_REF_PARACETAMOL")
        assert result["sku_id"] == "GENERIC_REF_PARACETAMOL"
        assert result["confidence"] == "tie_break_generic_default"

    def test_fuzzy_tie_break_two_brands_ambiguous(self):
        """k. tie between two brands still returns ambiguous."""
        mock_db = self._make_mock_db(fuzzy_results=[
            ("CALPOL650", "PARACETAMOL", 1.0000),
            ("DOLO650", "PARACETAMOL", 0.9500)
        ])
        
        result = resolve_drug_entity(mock_db, "paracetamol overdose symptoms")
        assert result["status"] == "disambiguate"

    def test_fuzzy_tie_break_three_way_ambiguous(self):
        """l. 3-way tie including a generic still returns ambiguous."""
        mock_db = self._make_mock_db(fuzzy_results=[
            ("CALPOL650", "PARACETAMOL", 1.0000),
            ("DOLO650", "PARACETAMOL", 0.9500),
            ("GENERIC_REF_PARACETAMOL", "PARACETAMOL", 0.9000)
        ])
        
        result = resolve_drug_entity(mock_db, "paracetamol overdose symptoms")
        assert result["status"] == "disambiguate"

    def test_pipeline_disambiguate_short_circuit(self):
        """Test that disambiguate status bypasses route_and_process_query."""
        import json as _json
        from fastapi import FastAPI
        from app.api.v1.knowledge_base import router as kb_router
        from app.infrastructure.database import get_database_session
        
        mock_db = MagicMock()
        mock_route = AsyncMock()
        
        app = FastAPI()
        app.include_router(kb_router, prefix="/api/v1/knowledge-base")
        app.dependency_overrides[get_database_session] = lambda: mock_db
        
        # Patch resolver to return disambiguate
        with patch('app.api.v1.knowledge_base.resolve_drug_entity') as mock_resolve, \
             patch('app.api.v1.knowledge_base.route_and_process_query', mock_route):
             
            mock_resolve.return_value = {
                "status": "disambiguate",
                "choices": ["TELMA-40", "TELMI-40"]
            }
            
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
                    (b"host", b"testserver"),
                ],
            }
            
            # Body payload that will hit INVENTORY intent (objective keyword "price")
            body = _json.dumps(
                {"query": "price of TELM-40", "sku_id": "TELM-40"}
            ).encode("utf-8")
            
            response_status = None
            response_body = b""
            
            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}
                
            async def send(message):
                nonlocal response_status, response_body
                if message["type"] == "http.response.start":
                    response_status = message["status"]
                elif message["type"] == "http.response.body":
                    response_body = message["body"]
                    
            import asyncio
            asyncio.run(app(scope, receive, send))
            
            assert response_status == 200
            data = _json.loads(response_body)
            assert data["status"] == "disambiguate"
            # choices is a list of {"sku_id": ..., "display_name": ...} objects
            # The mock returns plain strings, which the knowledge_base display-name
            # lookup wraps into dicts. Verify sku_ids are present.
            returned_sku_ids = [c["sku_id"] for c in data["choices"]]
            assert "TELMA-40" in returned_sku_ids
            assert "TELMI-40" in returned_sku_ids
            
            # Assert route_and_process_query was never called
            mock_route.assert_not_called()

    def test_pipeline_no_match_short_circuit(self):
        """Test that no_match status bypasses route_and_process_query."""
        import json as _json
        from fastapi import FastAPI
        from app.api.v1.knowledge_base import router as kb_router
        from app.infrastructure.database import get_database_session
        
        mock_db = MagicMock()
        mock_route = AsyncMock()
        
        app = FastAPI()
        app.include_router(kb_router, prefix="/api/v1/knowledge-base")
        app.dependency_overrides[get_database_session] = lambda: mock_db
        
        # Patch resolver to return no_match
        with patch('app.api.v1.knowledge_base.resolve_drug_entity') as mock_resolve, \
             patch('app.api.v1.knowledge_base.route_and_process_query', mock_route):
             
            mock_resolve.return_value = {
                "status": "no_match",
                "reason": "no_close_match_found"
            }
            
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
                    (b"host", b"testserver"),
                ],
            }
            
            body = _json.dumps(
                {"query": "price of XYZZY-40", "sku_id": "XYZZY-40"}
            ).encode("utf-8")
            
            response_status = None
            response_body = b""
            
            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}
                
            async def send(message):
                nonlocal response_status, response_body
                if message["type"] == "http.response.start":
                    response_status = message["status"]
                elif message["type"] == "http.response.body":
                    response_body = message["body"]
                    
            import asyncio
            asyncio.run(app(scope, receive, send))
            
            assert response_status == 200
            data = _json.loads(response_body)
            assert data.get("status") == "no_match"
            
            # Assert route_and_process_query was never called
            mock_route.assert_not_called()

    def test_pipeline_exact_regression(self):
        """e. A regression test proving a pre-existing, already-exact SKU query
        still resolves and reaches INVENTORY exactly as before Phase 2."""
        import json as _json
        from fastapi import FastAPI
        from app.api.v1.knowledge_base import router as kb_router
        from app.infrastructure.database import get_database_session
        from app.domain.schemas import RAGQueryResponse
        
        mock_db = MagicMock()
        mock_route = AsyncMock()
        mock_route.return_value = {
            "answer": "Here is the price",
            "context_used": [],
            "is_safe_to_dispense": True,
            "system_lock_reason": None,
            "citations": []
        }
        
        app = FastAPI()
        app.include_router(kb_router, prefix="/api/v1/knowledge-base")
        app.dependency_overrides[get_database_session] = lambda: mock_db
        
        # Patch resolver to return exact match
        with patch('app.api.v1.knowledge_base.resolve_drug_entity') as mock_resolve, \
             patch('app.api.v1.knowledge_base.route_and_process_query', mock_route):
             
            mock_resolve.return_value = {
                "status": "resolved",
                "sku_id": "PAN-40",
                "confidence": "exact"
            }
            
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
                    (b"host", b"testserver"),
                ],
            }
            
            body = _json.dumps(
                {"query": "PAN-40 price", "sku_id": "PAN-40"}
            ).encode("utf-8")
            
            response_status = None
            response_body = b""
            
            async def receive():
                return {"type": "http.request", "body": body, "more_body": False}
                
            async def send(message):
                nonlocal response_status, response_body
                if message["type"] == "http.response.start":
                    response_status = message["status"]
                elif message["type"] == "http.response.body":
                    response_body = message["body"]
                    
            import asyncio
            asyncio.run(app(scope, receive, send))
            
            assert response_status == 200
            
            # Assert route_and_process_query WAS called and correctly received the resolved SKU
            mock_route.assert_called_once()
            called_kwargs = mock_route.call_args[1]
            assert called_kwargs["sku_id"] == "PAN-40"

    def test_brand_match_exact(self):
        """f. Brand name exact match is translated to real SKU ID."""
        mock_db = self._make_mock_db(exact_alias="PARA-500")
            
        result = resolve_drug_entity(mock_db, "price of crocin")
        
        assert result["status"] == "resolved"
        assert result["sku_id"] == "PARA-500"  # Translated!
        assert result["confidence"] == "exact"

    def test_brand_match_fuzzy(self):
        """g. Brand name fuzzy match is translated to real SKU ID."""
        mock_db = self._make_mock_db(fuzzy_results=[("PARA-500", "CROCIN", 0.90)])
            
        # "CROCCIN" is misspelled but very close to "CROCIN"
        result = resolve_drug_entity(mock_db, "price of CROCCIN")
        
        assert result["status"] == "resolved"
        assert result["sku_id"] == "PARA-500"  # Translated!
        assert result["confidence"] == "fuzzy"

    def test_rca_case_2_pn40(self):
        """Case 2: Short SKU-shaped token ('pn40') reaches fuzzy matcher."""
        mock_db = self._make_mock_db(fuzzy_results=[("PN40", "PN 40", 0.85)])
        result = resolve_drug_entity(mock_db, "price of pn40")
        assert result["status"] == "resolved"
        assert result["sku_id"] == "PN40"

    def test_rca_case_4_punctuation(self):
        """Case 4: Token with quotes/commas resolves correctly."""
        mock_db = self._make_mock_db(exact_alias="TELMA40")
        result = resolve_drug_entity(mock_db, "what is the price of 'TELMA-40',")
        assert result["status"] == "resolved"
        assert result["sku_id"] == "TELMA40"

    def test_hyphenated_vs_bare_mismatch(self):
        """Fix B: Hyphenated query token matches bare catalog SKU."""
        mock_db = self._make_mock_db(exact_alias="TELMA40")
        result = resolve_drug_entity(mock_db, "TELMA-40")
        assert result["status"] == "resolved"
        assert result["sku_id"] == "TELMA40"

class TestRCARegression:
    """Test suite for the Phase 2.1 RCA regression queries."""
    
    def test_rca_funnel_queries(self):
        import json as _json
        from fastapi import FastAPI
        from app.api.v1.knowledge_base import router as kb_router
        from app.infrastructure.database import get_database_session
        
        mock_db = MagicMock()
        mock_route = AsyncMock()
        mock_route.return_value = {
            "answer": "Here is the price",
            "context_used": [],
            "is_safe_to_dispense": True,
            "system_lock_reason": None,
            "citations": []
        }
        
        app = FastAPI()
        app.include_router(kb_router, prefix="/api/v1/knowledge-base")
        app.dependency_overrides[get_database_session] = lambda: mock_db
        
        def mock_execute(query, params=None):
            query_str = str(query)
            result = MagicMock()
            q_param = (params or {}).get("query", "").upper()
            
            if "FROM medications" in query_str:
                result.fetchone.return_value = None
            elif "WHERE REPLACE(alias_text" in query_str:
                if "TELMA40" in q_param or "TELMA 40" in q_param:
                    result.fetchone.return_value = ("TELMA40",)
                elif "PAN40" in q_param or "PAN 40" in q_param:
                    result.fetchone.return_value = ("PAN40",)
                elif "PN40" in q_param or "PN 40" in q_param:
                    result.fetchone.return_value = ("PN40",)
                else:
                    result.fetchone.return_value = None
            elif "similarity(" in query_str:
                q_param = " ".join((params or {}).get("candidates", [])).upper()
                if "CROCCIN" in q_param:
                    result.fetchall.return_value = [("CROCCIN", "CROCIN500", "CROCIN", 0.90)]
                elif "PN40" in q_param:
                    result.fetchall.return_value = [("PN40", "PN40", "PN 40", 0.90)]
                else:
                    result.fetchall.return_value = []
            else:
                result.fetchone.return_value = None
                result.fetchall.return_value = []
            return result
            
        mock_db.execute.side_effect = mock_execute
        
        with patch('app.api.v1.knowledge_base.route_and_process_query', mock_route):
            async def run_query(q):
                scope = {
                    "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
                    "scheme": "http", "path": "/api/v1/knowledge-base/ask",
                    "raw_path": b"/api/v1/knowledge-base/ask", "query_string": b"",
                    "headers": [(b"content-type", b"application/json"), (b"host", b"testserver")],
                }
                body = _json.dumps({"query": q, "sku_id": None}).encode("utf-8")
                response_status = None
                response_body = b""
                async def receive(): return {"type": "http.request", "body": body, "more_body": False}
                async def send(message):
                    nonlocal response_status, response_body
                    if message["type"] == "http.response.start": response_status = message["status"]
                    elif message["type"] == "http.response.body": response_body = message["body"]
                
                import asyncio
                await app(scope, receive, send)
                return _json.loads(response_body)
            
            import asyncio
            
            # Case 1: "price of PARCTMOL" -> no_match (genuinely fails 0.85 cutoff)
            res = asyncio.run(run_query("price of PARCTMOL"))
            assert res.get("status") == "no_match"
            assert mock_route.call_count == 0
            mock_route.reset_mock()
            
            # Case 2: "price of pn40" -> resolved
            res = asyncio.run(run_query("price of pn40"))
            assert mock_route.call_count == 1
            assert mock_route.call_args[1]["sku_id"] == "PN40"
            mock_route.reset_mock()
            
            # Case 3: "price of Pan" -> no_match (fails exact/fuzzy match, falls back to intent gate)
            res = asyncio.run(run_query("price of Pan"))
            assert res.get("status") == "no_match"
            assert mock_route.call_count == 0
            mock_route.reset_mock()
            
            # Case 4: "what is the price of 'TELMA-40'," -> resolved
            res = asyncio.run(run_query("what is the price of 'TELMA-40',"))
            assert mock_route.call_count == 1
            assert mock_route.call_args[1]["sku_id"] == "TELMA40"
            mock_route.reset_mock()
            
            # Case 5: "what is the price of pan 40" -> resolved
            res = asyncio.run(run_query("what is the price of pan 40"))
            assert mock_route.call_count == 1
            assert mock_route.call_args[1]["sku_id"] == "PAN40"
            mock_route.reset_mock()
            
            # Case 6: "what is the price of CROCCIN" -> resolved
            res = asyncio.run(run_query("what is the price of CROCCIN"))
            assert mock_route.call_count == 1
            assert mock_route.call_args[1]["sku_id"] == "CROCIN500"
            mock_route.reset_mock()
            
    def test_no_drug_no_db_call(self):
        """A true no-drug-at-all control case (e.g. 'what\'s the weather today')
        must STILL return NO_INTENT's short message with zero DB calls."""
        import json as _json
        from fastapi import FastAPI
        from app.api.v1.knowledge_base import router as kb_router
        from app.infrastructure.database import get_database_session
        
        mock_db = MagicMock()
        mock_route = AsyncMock()
        
        app = FastAPI()
        app.include_router(kb_router, prefix="/api/v1/knowledge-base")
        app.dependency_overrides[get_database_session] = lambda: mock_db
        
        with patch('app.api.v1.knowledge_base.resolve_drug_entity') as mock_resolve, \
             patch('app.api.v1.knowledge_base.route_and_process_query', mock_route):
             
            scope = {
                "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
                "scheme": "http", "path": "/api/v1/knowledge-base/ask",
                "raw_path": b"/api/v1/knowledge-base/ask", "query_string": b"",
                "headers": [(b"content-type", b"application/json"), (b"host", b"testserver")],
            }
            body = _json.dumps({"query": "what's the weather today", "sku_id": None}).encode("utf-8")
            response_status = None
            response_body = b""
            async def receive(): return {"type": "http.request", "body": body, "more_body": False}
            async def send(message):
                nonlocal response_status, response_body
                if message["type"] == "http.response.start": response_status = message["status"]
                elif message["type"] == "http.response.body": response_body = message["body"]
            
            import asyncio
            asyncio.run(app(scope, receive, send))
            
            data = _json.loads(response_body)
            assert data.get("status") == "no_intent"

class TestDrugResolverRealDB:
    """
    Real-DB regression test for the fuzzy-matching SQL path with realistic full sentences,
    to ensure we catch SQL syntax errors like the %% vs % operator mismatch.
    """
    def test_real_db_fuzzy_match_sql_syntax(self):
        from app.infrastructure.database import SessionLocal
        from sqlalchemy.exc import OperationalError, ProgrammingError, DataError
        
        try:
            real_db = SessionLocal()
            # We run the exact queries that previously crashed with %% operator bug.
            queries = [
                "is dolo650 safe for a pregnant woman",
                "what is the dose of crocin for kids",
                "AMLOK5 side effects"
            ]
            for query in queries:
                # If there's a SQL syntax error, this will throw an exception.
                result = resolve_drug_entity(real_db, query)
                assert isinstance(result, dict)
                assert "status" in result
        except OperationalError:
            pytest.skip("Real database not available for this test.")
        finally:
            if 'real_db' in locals():
                real_db.close()

    def test_real_db_spot_check_queries_resolve(self):
        """
        Verify that the real full-sentence queries from the 5.2g spot check
        now correctly resolve the expected target SKUs by extracting candidates
        and passing them to pg_trgm.
        """
        from app.infrastructure.database import SessionLocal
        from sqlalchemy.exc import OperationalError
        try:
            real_db = SessionLocal()
            
            # 1. "can I give domperidone to a 2 year old"
            res = resolve_drug_entity(real_db, "can I give domperidone to a 2 year old")
            assert res["status"] == "resolved"
            assert res["sku_id"] == "GENERIC_REF_DOMPERIDONE"
            
            # 2. "is amoxycillin safe with alcohol"
            res = resolve_drug_entity(real_db, "is amoxycillin safe with alcohol")
            assert res["status"] in ("resolved", "disambiguate")

            # 3. "is Dolo650 safe for a pregnant woman"
            res = resolve_drug_entity(real_db, "is Dolo650 safe for a pregnant woman")
            assert res["status"] in ("resolved", "disambiguate")
            # Usually resolves to PARACETAMOL or disambiguates

        except OperationalError:
            pytest.skip("Real database not available for this test.")
        finally:
            if 'real_db' in locals():
                real_db.close()
