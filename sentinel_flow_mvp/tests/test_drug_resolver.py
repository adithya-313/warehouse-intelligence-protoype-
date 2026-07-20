import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from app.domain.drug_resolver import resolve_drug_entity

class TestDrugResolver:
    """Test suite for the fuzzy drug resolver (Phase 2)."""

    def test_exact_match(self):
        """a. Exact match → status 'resolved', confidence 'exact'."""
        mock_db = MagicMock()
        
        with patch('app.domain.drug_resolver.get_known_drug_catalog') as mock_catalog, \
             patch('app.domain.drug_resolver.translate_to_sku', side_effect=lambda db, m, skus: m):
            mock_catalog.return_value = ({"PAN-40", "TELMA-40"}, {"CROCIN", "CALPOL"})
            
            result = resolve_drug_entity(mock_db, "price of pan-40")
            assert result["status"] == "resolved"
            assert result["sku_id"] == "PAN-40"
            assert result["confidence"] == "exact"

    def test_fuzzy_match_single(self):
        """b. Deliberately misspelled real drug name (single close match) → status 'resolved', confidence 'fuzzy'."""
        mock_db = MagicMock()
        
        with patch('app.domain.drug_resolver.get_known_drug_catalog') as mock_catalog, \
             patch('app.domain.drug_resolver.translate_to_sku', side_effect=lambda db, m, skus: m):
            mock_catalog.return_value = ({"PAN-40", "TELMA-40", "PARACETAMOL"}, set())
            
            # Note: cutoff is 0.85, so we need a very close misspelling.
            # "PARACETAMOL" vs "PARCETAMOL" ratio is ~0.95
            result = resolve_drug_entity(mock_db, "price of PARCETAMOL")
            assert result["status"] == "resolved"
            assert result["sku_id"] == "PARACETAMOL"
            assert result["confidence"] == "fuzzy"

    def test_disambiguate_multiple_matches(self):
        """c. Deliberately misspelled name with 2+ plausible matches → status 'disambiguate'."""
        mock_db = MagicMock()
        
        with patch('app.domain.drug_resolver.get_known_drug_catalog') as mock_catalog, \
             patch('app.domain.drug_resolver.translate_to_sku', side_effect=lambda db, m, skus: m):
            mock_catalog.return_value = ({"TELMA-40", "TELMA-80", "TELMI-40"}, set())
            
            # TELM-40 is very close to TELMA-40 and TELMI-40 (ratio > 0.85)
            # TELMA-40 ratio: 0.93, TELMI-40 ratio: 0.93
            result = resolve_drug_entity(mock_db, "price of TELM-40")
            assert result["status"] == "disambiguate"
            assert "choices" in result
            assert 2 <= len(result["choices"]) <= 3
            assert "TELMA-40" in result["choices"]

    def test_no_match_gibberish(self):
        """d. Gibberish input with zero plausible matches → status 'no_match'."""
        mock_db = MagicMock()
        
        with patch('app.domain.drug_resolver.get_known_drug_catalog') as mock_catalog, \
             patch('app.domain.drug_resolver.translate_to_sku', side_effect=lambda db, m, skus: m):
            mock_catalog.return_value = ({"PAN-40", "TELMA-40"}, set())
            
            result = resolve_drug_entity(mock_db, "price of xyzzy1234")
            assert result["status"] == "no_match"
            assert result["reason"] == "no_close_match_found"

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
            assert data["choices"] == ["TELMA-40", "TELMI-40"]
            
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
        mock_db = MagicMock()
        
        # Setup mock DB response for translate_to_sku
        class MockRow:
            def __init__(self, sku_id, brand_name):
                self.sku_id = sku_id
                self.metadata_payload = {"brand_name": brand_name}
                
        mock_ckb_query = MagicMock()
        mock_ckb_query.all.return_value = [
            MockRow("PARA-500", "CROCIN"),
            MockRow("TELM-40", "TELMA")
        ]
        
        # When querying CKB, return our mock query
        mock_db.query.return_value = mock_ckb_query
        
        with patch('app.domain.drug_resolver.get_known_drug_catalog') as mock_catalog:
            mock_catalog.return_value = ({"PARA-500", "TELM-40"}, {"CROCIN", "TELMA"})
            
            result = resolve_drug_entity(mock_db, "price of crocin")
            
            assert result["status"] == "resolved"
            assert result["sku_id"] == "PARA-500"  # Translated!
            assert result["confidence"] == "exact"
            
            # Verify subsequent DB lookup for the returned SKU would work by asserting
            # that we queried the DB and found it.
            # In our mock, CROCIN mapped to PARA-500. We assert that mock_db.query was called.
            mock_db.query.assert_called()

    def test_brand_match_fuzzy(self):
        """g. Brand name fuzzy match is translated to real SKU ID."""
        mock_db = MagicMock()
        
        class MockRow:
            def __init__(self, sku_id, brand_name):
                self.sku_id = sku_id
                self.metadata_payload = {"brand_name": brand_name}
                
        mock_ckb_query = MagicMock()
        mock_ckb_query.all.return_value = [
            MockRow("PARA-500", "CROCIN"),
            MockRow("TELM-40", "TELMA")
        ]
        
        mock_db.query.return_value = mock_ckb_query
        
        with patch('app.domain.drug_resolver.get_known_drug_catalog') as mock_catalog:
            mock_catalog.return_value = ({"PARA-500", "TELM-40"}, {"CROCIN", "TELMA"})
            
            # "CROCCIN" is misspelled but very close to "CROCIN"
            result = resolve_drug_entity(mock_db, "price of CROCCIN")
            
            assert result["status"] == "resolved"
            assert result["sku_id"] == "PARA-500"  # Translated!
            assert result["confidence"] == "fuzzy"
            
            mock_db.query.assert_called()
