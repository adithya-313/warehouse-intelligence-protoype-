"""
Unit tests for the Adaptive Routing system (route_and_process_query).

Focus Area: LLM Bypass — Objective queries must be answered from the database
without ever calling the Gemini API.

Beginner Note: These tests prove that our "Traffic Cop" routing works correctly.
The most important test is the Objective Routing test because it confirms we
save money and latency by not calling Gemini for simple price/stock questions.

Every test follows the Arrange-Act-Assert (AAA) pattern.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import date


class TestAdaptiveRoutingObjective:
    """
    Tests for objective (database) queries.

    Verifies that when a user asks about price, stock, MRP, or other
    factual data, the router answers from the database WITHOUT calling
    the Gemini API.
    """

    @pytest.mark.anyio
    async def test_objective_mrp_query_returns_database_answer(self):
        """
        ARRANGE: Create a mock database session that returns a batch with
        known MRP and stock values. The query contains the keyword "mrp"
        and a sku_id is provided.

        ACT: Call route_and_process_query with the objective query.

        ASSERT: The answer contains the MRP value from the database.
        The Gemini function was NEVER called (saving $ and latency).
        """
        # ==================================================================
        # ARRANGE: Build a mock database with one medication batch
        # ==================================================================
        mock_db = MagicMock()

        # Create a fake batch record with known values
        mock_batch = MagicMock()
        mock_batch.sku_id = "SKU-001"
        mock_batch.batch_id = "BATCH-001"
        mock_batch.max_retail_price = 45.00
        mock_batch.available_quantity = 120
        mock_batch.expiry_date = date(2027, 6, 15)
        mock_batch.cost_price = 30.00
        mock_batch.shelf_location = "SHELF-A1"

        # Configure the query chain: .query().filter().order_by().all()
        # returns our single mock batch
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            mock_batch
        ]

        # ==================================================================
        # ACT & ASSERT: Route the objective query
        # ==================================================================
        # We patch generate_clinical_response with a sentinel mock so we can
        # verify it was NEVER called — the answer must come from the database.
        with patch(
            "app.services.rag_pipeline.generate_clinical_response",
        ) as mock_gemini:
            from app.services.rag_pipeline import route_and_process_query

            result = await route_and_process_query(
                db=mock_db,
                query="What is the MRP for this medication?",
                sku_id="SKU-001",
            )

            # --- Assertion 1: Gemini was never called ---
            mock_gemini.assert_not_called()
            assert mock_gemini.call_count == 0, (
                "The objective query matched 'mrp' and a sku_id was provided. "
                "Gemini should NOT have been called."
            )

            # --- Assertion 2: The answer came from the database ---
            assert "MRP" in result["answer"], (
                f"Expected the answer to contain 'MRP'. Got: {result['answer']}"
            )
            assert "45.00" in result["answer"], (
                f"Expected the answer to contain '45.00'. Got: {result['answer']}"
            )
            assert "120" in result["answer"], (
                f"Expected the answer to mention stock quantity '120'. Got: {result['answer']}"
            )

            # --- Assertion 3: context_used is empty (no RAG context) ---
            assert result["context_used"] == [], (
                "Objective queries should return an empty context_used list "
                "because no RAG pipeline was executed."
            )

    @pytest.mark.anyio
    async def test_objective_stock_query_returns_database_answer(self):
        """
        ARRANGE: Same as above, but the query uses the "stock" keyword.

        ACT: Call route_and_process_query.

        ASSERT: Answer contains stock data. Gemini not called.
        """
        mock_db = MagicMock()
        mock_batch = MagicMock()
        mock_batch.sku_id = "SKU-001"
        mock_batch.batch_id = "BATCH-001"
        mock_batch.max_retail_price = 45.00
        mock_batch.available_quantity = 120
        mock_batch.expiry_date = date(2027, 6, 15)
        mock_batch.cost_price = 30.00
        mock_batch.shelf_location = "SHELF-A1"

        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            mock_batch
        ]

        with patch("app.services.rag_pipeline.generate_clinical_response") as mock_gemini:
            from app.services.rag_pipeline import route_and_process_query

            result = await route_and_process_query(
                db=mock_db,
                query="How many units are in stock?",
                sku_id="SKU-001",
            )

            mock_gemini.assert_not_called()
            assert "120" in result["answer"]
            assert result["context_used"] == []

    @pytest.mark.anyio
    async def test_objective_query_without_sku_id_falls_to_gemini(self):
        """
        ARRANGE: Query contains an objective keyword ("price") but NO
        sku_id is provided.

        ACT: Call route_and_process_query.

        ASSERT: The query falls through to Gemini because we cannot query
        the database without knowing which medication the user is asking about.
        """
        mock_db = MagicMock()

        with patch(
            "app.services.rag_pipeline.generate_clinical_response",
            return_value={
                "answer": "AI-generated answer about pricing",
                "context_used": [{"content": "clinical context"}],
            },
        ) as mock_gemini:
            from app.services.rag_pipeline import route_and_process_query

            result = await route_and_process_query(
                db=mock_db,
                query="What is the price?",
                sku_id=None,  # No SKU provided
            )

            # Even though "price" is an objective keyword, without a sku_id
            # we cannot query the database, so we fall through to Gemini.
            mock_gemini.assert_called_once()
            assert result["answer"] == "AI-generated answer about pricing"


class TestAdaptiveRoutingSubjective:
    """
    Tests for subjective (clinical) queries.

    Verifies that when a user asks a clinical question, the router correctly
    delegates to the Gemini RAG pipeline.
    """

    @pytest.mark.anyio
    async def test_clinical_query_calls_gemini_rag(self):
        """
        ARRANGE: Query contains NO objective keywords (MRP, price, stock, etc.)
        It is a purely clinical question about drug safety during pregnancy.

        ACT: Call route_and_process_query.

        ASSERT: The Gemini RAG pipeline was called exactly once and the
        response is the AI-generated answer.
        """
        # ==================================================================
        # ARRANGE: No database setup needed — the clinical route uses the
        # existing RAG pipeline which handles search internally.
        # ==================================================================
        mock_db = MagicMock()

        expected_answer = "Paracetamol is generally considered safe during pregnancy when used at therapeutic doses."
        expected_context = [{"content": "FDA Pregnancy Category B for Paracetamol"}]

        with patch(
            "app.services.rag_pipeline.generate_clinical_response",
            return_value={
                "answer": expected_answer,
                "context_used": expected_context,
            },
        ) as mock_gemini:
            from app.services.rag_pipeline import route_and_process_query

            # ==================================================================
            # ACT: Call the routing function with a clinical query
            # ==================================================================
            result = await route_and_process_query(
                db=mock_db,
                query="Is paracetamol safe for a pregnant patient?",
                sku_id="SKU-001",
            )

            # ==================================================================
            # ASSERT: Gemini was called exactly once
            # ==================================================================
            mock_gemini.assert_called_once()

            # The args passed to generate_clinical_response should include
            # the original query and sku_id
            call_args, call_kwargs = mock_gemini.call_args
            assert call_kwargs["query"] == "Is paracetamol safe for a pregnant patient?"
            assert call_kwargs["sku_id"] == "SKU-001"

            # The response should be the AI-generated answer
            assert result["answer"] == expected_answer
            assert result["context_used"] == expected_context

    @pytest.mark.anyio
    async def test_clinical_query_no_sku_id_still_calls_gemini(self):
        """
        ARRANGE: Clinical query with NO objective keywords and NO sku_id.

        ACT: Call route_and_process_query.

        ASSERT: Gemini is called — without a keyword match and without a
        sku_id, there is no reason to query the database. This is a pure
        clinical question that requires AI reasoning.
        """
        mock_db = MagicMock()

        with patch(
            "app.services.rag_pipeline.generate_clinical_response",
            return_value={
                "answer": "AI answer about drug interactions",
                "context_used": [],
            },
        ) as mock_gemini:
            from app.services.rag_pipeline import route_and_process_query

            result = await route_and_process_query(
                db=mock_db,
                query="Can this be taken with metformin?",
                sku_id=None,
            )

            mock_gemini.assert_called_once()
            assert result["answer"] == "AI answer about drug interactions"

class TestClinicalNarrationStockInjection:
    """
    Tests for Phase 3 stock injection into the clinical narration path.
    """

    @pytest.mark.anyio
    async def test_clinical_response_includes_stock_when_available(self):
        """
        ARRANGE: Mock the DB and get_optimal_fefo_batch to return stock data.
                 Mock execute_clinical_search to return a clinical context item.
        
        ACT: Call generate_clinical_response.
        
        ASSERT: The injected stock text appears in the context given to Gemini.
        """
        mock_db = MagicMock()
        
        with patch("app.services.rag_pipeline.get_optimal_fefo_batch") as mock_fefo, \
             patch("app.services.semantic_search.execute_clinical_search") as mock_search, \
             patch("google.genai.Client") as mock_client_class:
            
            # Setup semantic search mock
            mock_search.return_value = {"results": [{"content": "clinical data", "sku_id": "SKU-001"}]}
            
            # Setup FEFO stock mock
            mock_fefo.return_value = {
                "available_quantity": 100,
                "max_retail_price": 50.0,
                "expiry_date": date(2027, 12, 1)
            }
            
            # Setup Gemini mock
            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance
            mock_generate_content = mock_client_instance.models.generate_content
            mock_generate_content.return_value = MagicMock(
                text='{"is_safe_to_dispense": true, "narrative": "AI response", "system_lock_reason": null, "citations": []}'
            )
            
            from app.services.rag_pipeline import generate_clinical_response
            
            result = await generate_clinical_response(
                db=mock_db,
                query="Is this safe?",
                sku_id="SKU-001"
            )
            
            mock_generate_content.assert_called_once()
            call_kwargs = mock_generate_content.call_args[1]
            prompt_text = call_kwargs["contents"]
            
            assert "In stock:" not in prompt_text
            assert len(result["context_used"]) == 1
            assert result["context_used"][0]["stock_qty"] == 100
            assert result["context_used"][0]["unit_price"] == 50.0

    @pytest.mark.anyio
    async def test_clinical_response_handles_missing_stock_gracefully(self):
        """
        ARRANGE: Mock get_optimal_fefo_batch to return None (no stock).
        
        ACT: Call generate_clinical_response.
        
        ASSERT: The RAG pipeline still works, but no stock info is injected.
        """
        mock_db = MagicMock()
        
        with patch("app.services.rag_pipeline.get_optimal_fefo_batch") as mock_fefo, \
             patch("app.services.semantic_search.execute_clinical_search") as mock_search, \
             patch("google.genai.Client") as mock_client_class:
            
            # Setup semantic search mock
            mock_search.return_value = {"results": [{"content": "clinical data", "sku_id": "SKU-001"}]}
            
            # Setup FEFO stock mock to return None
            mock_fefo.return_value = None
            
            # Setup Gemini mock
            mock_client_instance = MagicMock()
            mock_client_class.return_value = mock_client_instance
            mock_generate_content = mock_client_instance.models.generate_content
            mock_generate_content.return_value = MagicMock(
                text='{"is_safe_to_dispense": true, "narrative": "AI response", "system_lock_reason": null, "citations": []}'
            )
            
            from app.services.rag_pipeline import generate_clinical_response
            
            result = await generate_clinical_response(
                db=mock_db,
                query="Is this safe?",
                sku_id="SKU-001"
            )
            
            mock_generate_content.assert_called_once()
            call_kwargs = mock_generate_content.call_args[1]
            prompt_text = call_kwargs["contents"]
            
            assert "In stock:" not in prompt_text
            assert "clinical data" in prompt_text
            
            assert len(result["context_used"]) == 1
            assert "stock_qty" not in result["context_used"][0]
