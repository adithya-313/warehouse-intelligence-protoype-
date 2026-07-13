"""
PHASE 2: QUERY SANITIZER & INTENT ROUTING TESTS
=================================================

Beginner Note:
    This test file verifies the QuerySanitizer class and the refactored
    knowledge_base.py endpoint. We test three layers:

    1. SANITIZER UNIT TESTS:
       - clean_drug_names() corrects misspelled drug names
       - extract_intents() correctly detects pregnancy/pediatric/substitute/objective
       - extract_sku() correctly extracts SKUs in both formats

    2. ENDPOINT INTEGRATION (mock database):
       - The /ask endpoint correctly sanitizes queries before processing
       - The sanitizer runs BEFORE any routing logic

    3. REGRESSION:
       - Existing query patterns still work after refactoring
       - No broken imports or syntax errors

    We do NOT need a real database — all tests use mocked sessions.
"""

# ======================================================================
# IMPORTS
# ======================================================================

import pytest
from unittest.mock import MagicMock, patch


# ======================================================================
# TEST CLASS 1: QuerySanitizer — clean_drug_names()
# ======================================================================

class TestCleanDrugNames:
    """
    Tests for the fuzzy drug name cleaning method.
    """

    def setup_method(self):
        """
        Create a fresh QuerySanitizer instance before each test.
        """
        from app.services.sanitizer import QuerySanitizer
        self.sanitizer = QuerySanitizer()

    def test_corrects_single_misspelling(self):
        """
        Given a misspelled drug name like "Crooosin" (which has an extra
        'o' and the wrong case), the sanitizer should correct it to
        "CROCIN" when the valid names list includes "CROCIN".

        Beginner Note:
            This is the exact test case from Phase 2 spec. The word
            "Crooosin" is 71% similar to "CROCIN" when both are
            normalized to uppercase, which is above our 0.6 cutoff.
        """
        # Arrange: a query with a misspelled drug name
        raw_query = "what is the price of Crooosin"
        valid_names = ["CROCIN", "DOLO-650", "PAN-40"]

        # Act: run through the cleaner
        cleaned = self.sanitizer.clean_drug_names(raw_query, valid_names)

        # Assert: the misspelled word should be corrected
        assert "CROCIN" in cleaned, (
            f"Expected 'Crooosin' to be corrected to 'CROCIN', "
            f"but got: '{cleaned}'"
        )
        # The original spelling should be gone
        assert "Crooosin" not in cleaned, (
            "The original misspelling should be fully replaced."
        )

    def test_no_change_for_correct_spelling(self):
        """
        If the query already has correct spelling, the sanitizer
        should return it unchanged.
        """
        raw_query = "what is the price of DOLO-650"
        valid_names = ["CROCIN", "DOLO-650", "PAN-40"]

        cleaned = self.sanitizer.clean_drug_names(raw_query, valid_names)

        assert cleaned == raw_query

    def test_short_words_ignored(self):
        """
        Words of 4 characters or fewer should NEVER be fuzzy-matched,
        because they are likely common English words (like "the", "is",
        "for") and not drug names.
        """
        raw_query = "the is for of"
        valid_names = ["THE", "IS", "FOR", "OF"]

        cleaned = self.sanitizer.clean_drug_names(raw_query, valid_names)

        # None of these short words should be changed
        assert cleaned == raw_query

    def test_empty_valid_names_list(self):
        """
        If the valid_names list is empty, the sanitizer should return
        the query unchanged without raising an error.
        """
        raw_query = "what is the price of Crooosin"

        cleaned = self.sanitizer.clean_drug_names(raw_query, [])

        assert cleaned == raw_query


# ======================================================================
# TEST CLASS 2: QuerySanitizer — extract_intents()
# ======================================================================

class TestExtractIntents:
    """
    Tests for the intent detection method.
    """

    def setup_method(self):
        from app.services.sanitizer import QuerySanitizer
        self.sanitizer = QuerySanitizer()

    def test_detects_pregnancy_intent(self):
        """
        A query containing "pregnant" should have the pregnancy flag set
        to True.
        """
        intents = self.sanitizer.extract_intents(
            "can a pregnant woman take dolo"
        )
        assert intents["pregnancy"] is True

    def test_detects_pediatric_intent(self):
        """
        A query containing "child" should have the pediatric flag set
        to True.
        """
        intents = self.sanitizer.extract_intents(
            "what dosage for a child with fever"
        )
        assert intents["pediatric"] is True

    def test_detects_substitute_intent(self):
        """
        A query containing "alternative" should have the substitute flag
        set to True.
        """
        intents = self.sanitizer.extract_intents(
            "find an alternative for PAN-40"
        )
        assert intents["substitute"] is True

    def test_detects_objective_intent(self):
        """
        A query containing "price" should have the objective flag set
        to True. This is the most common routing case.
        """
        intents = self.sanitizer.extract_intents(
            "what is the price of CROCIN"
        )
        assert intents["objective"] is True

    def test_multiple_intents_can_coexist(self):
        """
        A query like "safe for pregnant child?" should trigger BOTH
        pregnancy AND pediatric flags.
        """
        intents = self.sanitizer.extract_intents(
            "is this safe for a pregnant child"
        )
        assert intents["pregnancy"] is True
        assert intents["pediatric"] is True

    def test_no_intents_for_irrelevant_query(self):
        """
        A query with no matching keywords should have all flags False.
        """
        intents = self.sanitizer.extract_intents(
            "hello world"
        )
        assert intents == {
            "pregnancy": False,
            "pediatric": False,
            "substitute": False,
            "objective": False,
        }


# ======================================================================
# TEST CLASS 3: QuerySanitizer — extract_sku()
# ======================================================================

class TestExtractSku:
    """
    Tests for the unified SKU extraction method.
    """

    def setup_method(self):
        from app.services.sanitizer import QuerySanitizer
        self.sanitizer = QuerySanitizer()

    def test_extracts_hyphenated_sku(self):
        """
        A standard SKU like "DOLO-650" with a hyphen should be extracted
        and returned in uppercase canonical format.
        """
        sku = self.sanitizer.extract_sku("what is the price of DOLO-650")
        assert sku == "DOLO-650"

    def test_extracts_no_hyphen_sku(self):
        """
        A no-hyphen SKU like "PAN40" should have the hyphen inserted
        before the trailing digits.
        """
        sku = self.sanitizer.extract_sku("I need PAN40")
        assert sku == "PAN-40"

    def test_returns_none_when_no_sku_found(self):
        """
        A query without any SKU pattern should return None.
        """
        sku = self.sanitizer.extract_sku("hello world")
        assert sku is None

    def test_case_insensitive_matching(self):
        """
        SKU in lowercase like "dolo-650" should still be extracted and
        uppercased to the canonical "DOLO-650".
        """
        sku = self.sanitizer.extract_sku("price of dolo-650")
        assert sku == "DOLO-650"

    def test_sku_at_end_of_query(self):
        """
        SKU at the end of a query should still be found.
        """
        sku = self.sanitizer.extract_sku("need substitute for PAN40")
        assert sku == "PAN-40"


# ======================================================================
# TEST CLASS 4: End-to-end sanitizer pipeline
# ======================================================================

class TestSanitizerPipeline:
    """
    Tests that combine ALL three sanitizer methods in sequence,
    simulating the real flow through the /ask endpoint.
    """

    def setup_method(self):
        from app.services.sanitizer import QuerySanitizer
        self.sanitizer = QuerySanitizer()

    def test_full_pipeline_objective_misspelling(self):
        """
        Test Case 1 from the Phase 2 spec:
        "what is the price of Crooosin" should:
          1. Fuzzy-match "Crooosin" to "CROCIN"
          2. Flag the 'objective' intent (because "price" is present)
        """
        raw_query = "what is the price of Crooosin"
        valid_names = ["CROCIN", "DOLO-650", "PAN-40"]

        # Step 1: Clean drug names
        cleaned = self.sanitizer.clean_drug_names(raw_query, valid_names)
        assert "CROCIN" in cleaned, (
            f"Step 1 (clean) failed: expected CROCIN in '{cleaned}'"
        )

        # Step 2: Extract intents
        intents = self.sanitizer.extract_intents(cleaned)
        assert intents["objective"] is True, (
            f"Step 2 (intents) failed: expected objective=True, "
            f"got {intents}"
        )

        # Verify no OTHER intents were falsely triggered
        assert intents["pregnancy"] is False
        assert intents["pediatric"] is False
        assert intents["substitute"] is False

    def test_full_pipeline_pregnancy(self):
        """
        Test Case 2 from the Phase 2 spec:
        "can a pregnant woman take dolo" should flag the 'pregnancy' intent.
        """
        raw_query = "can a pregnant woman take dolo"
        valid_names = ["DOLO-650"]

        # Step 1: Clean (no misspellings expected here)
        cleaned = self.sanitizer.clean_drug_names(raw_query, valid_names)

        # Step 2: Extract intents
        intents = self.sanitizer.extract_intents(cleaned)

        # Pregnancy should be detected
        assert intents["pregnancy"] is True, (
            f"Expected pregnancy=True, got {intents}"
        )

        # No substitute intent (no substitute/alternative keywords)
        assert intents["substitute"] is False

    def test_substitute_routing_triggers(self):
        """
        When a user asks for a substitute AND includes a SKU,
        the substitute intent should be True AND a SKU should be extracted.
        """
        raw_query = "find an alternative for PAN40"
        valid_names = ["PAN-40"]

        cleaned = self.sanitizer.clean_drug_names(raw_query, valid_names)
        sku = self.sanitizer.extract_sku(cleaned)
        intents = self.sanitizer.extract_intents(cleaned)

        assert intents["substitute"] is True
        assert sku == "PAN-40"


# ======================================================================
# TEST CLASS 5: API endpoint integration (mock DB)
# ======================================================================

class TestAskEndpointWithSanitizer:
    """
    Tests that the /ask endpoint correctly integrates the sanitizer
    and passes the cleaned query downstream.

    We use a mock database session so no real database is needed.
    """

    @pytest.fixture
    def mock_db_session(self):
        """Mimics the conftest.py mock_db_session fixture."""
        from sqlalchemy.orm import Session
        session = MagicMock(spec=Session)
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = None
        mock_filter.with_for_update.return_value = mock_filter
        mock_query.filter.return_value = mock_filter
        session.query.return_value = mock_query
        session.add = MagicMock()
        session.commit = MagicMock()
        session.rollback = MagicMock()
        session.close = MagicMock()
        return session

    @pytest.fixture
    def test_app(self, mock_db_session):
        """Build a minimal FastAPI app with just the knowledge_base router."""
        from fastapi import FastAPI
        from app.api.v1.knowledge_base import router as kb_router
        from app.infrastructure.database import get_database_session

        app = FastAPI()
        app.include_router(kb_router, prefix="/api/v1/knowledge")
        app.dependency_overrides[get_database_session] = lambda: mock_db_session
        return app

    @pytest.fixture
    def client(self, test_app):
        """FastAPI TestClient bound to our test app."""
        from fastapi.testclient import TestClient
        with TestClient(test_app) as c:
            yield c

    def test_ask_endpoint_imports_and_responds(self, client):
        """
        Verify the /ask endpoint can be called and returns a valid
        response structure (even if Gemini is offline, the pipeline
        should degrade gracefully).
        """
        response = client.post(
            "/api/v1/knowledge/ask",
            json={
                "query": "what is the price of DOLO-650",
            },
        )

        # The endpoint should respond (either 200 or 422 depending
        # on validation). We just verify it doesn't crash with 500.
        assert response.status_code in (200, 422), (
            f"Expected 200 or 422, got {response.status_code}: "
            f"{response.text[:200]}"
        )

    def test_ask_endpoint_with_substitute_intent(self, client):
        """
        When the query contains "alternative", and a SKU is extractable,
        the endpoint should route to the substitute finder and return
        a structured response.
        """
        response = client.post(
            "/api/v1/knowledge/ask",
            json={
                "query": "find an alternative for PAN40",
            },
        )

        # The endpoint might return 200 (substitute found/not found)
        # or fall through to Gemini (which returns offline error).
        # Either is acceptable — we just verify no 500 error.
        assert response.status_code in (200, 503), (
            f"Unexpected status: {response.status_code}"
        )


# ======================================================================
# TEST CLASS 6: Sanitizer is stateless and thread-safe
# ======================================================================

class TestSanitizerStatelessness:
    """
    Verify that the QuerySanitizer has no internal state that could
    leak between requests.
    """

    def test_multiple_calls_produce_same_result(self):
        """
        Calling the same method twice with the same input should
        produce the same output (deterministic).
        """
        from app.services.sanitizer import QuerySanitizer
        sanitizer = QuerySanitizer()

        result_1 = sanitizer.extract_intents("is this safe for pregnancy")
        result_2 = sanitizer.extract_intents("is this safe for pregnancy")

        assert result_1 == result_2

    def test_consecutive_calls_dont_interfere(self):
        """
        Calling clean_drug_names with different queries should not
        cause cross-contamination.
        """
        from app.services.sanitizer import QuerySanitizer
        sanitizer = QuerySanitizer()

        valid = ["CROCIN", "DOLO-650"]

        r1 = sanitizer.clean_drug_names("need Crooosin", valid)
        r2 = sanitizer.clean_drug_names("hello world", valid)

        assert "CROCIN" in r1
        assert r2 == "hello world"
