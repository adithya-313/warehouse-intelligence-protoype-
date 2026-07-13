"""
Phase 5 — Universal ETL Adapter Tests.

Beginner Note:
    This test file validates the TWO pure-Python functions in the ETL
    pipeline — ``transform_row()`` and ``create_semantic_chunk()``.
    We do NOT test embedding generation (that requires SentenceTransformer)
    or database loading (that requires PostgreSQL). We test only the
    deterministic, dependency-free data transformation logic.

    The strategy:
        - Pass a mock CSV row (a Python dictionary) through
          ``transform_row()`` and verify the output has the correct keys
          and default values.
        - Pass deliberately MISSING keys to prove the function does not
          crash.
        - Pass the transformed output through ``create_semantic_chunk()``
          and verify it returns a non-empty string containing key clinical
          information.
"""

import pytest

# Import the two pure functions from the ETL pipeline.
# These have ZERO external dependencies — no torch, no database, no Redis.
from scripts.etl_pipeline import transform_row, create_semantic_chunk


# =====================================================================
# TEST CLASS 1: transform_row — Happy Path
# =====================================================================

class TestTransformRowHappyPath:
    """Verify transform_row() works correctly with a complete CSV row."""

    def test_returns_sku_id(self):
        """GIVEN a CSV row with all fields
        WHEN transform_row() is called
        THEN the output MUST contain the correct sku_id.
        """
        mock_row = {
            "sku_id": "PAN40",
            "brand_name": "Pan 40",
            "generic_name": "Pantoprazole",
            "indications": "GERD; Acidity",
            "side_effects": "Headache; Nausea",
            "contraindications": "Severe liver disease",
            "price_inr": "135.00",
        }

        result = transform_row(mock_row)

        assert result["sku_id"] == "PAN40"

    def test_apis_contains_generic_name(self):
        """GIVEN a CSV row with generic_name
        WHEN transform_row() is called
        THEN the apis list MUST contain that generic name.
        """
        mock_row = {
            "sku_id": "GLYCOMET500",
            "brand_name": "Glycomet 500",
            "generic_name": "Metformin",
            "indications": "Type 2 Diabetes",
            "side_effects": "Nausea",
            "contraindications": "Renal impairment",
            "price_inr": "45.00",
        }

        result = transform_row(mock_row)

        assert "Metformin" in result["apis"]

    def test_supplies_safety_defaults(self):
        """GIVEN a CSV row WITHOUT pregnancy_category or pediatric fields
        WHEN transform_row() is called
        THEN the output MUST use the configured default values.
        """
        mock_row = {
            "sku_id": "TEST-001",
            "brand_name": "Test Drug",
            "generic_name": "Testolum",
            "indications": "Testing",
            "side_effects": "None",
            "contraindications": "None",
            "price_inr": "10.00",
        }

        result = transform_row(mock_row)

        assert result["pregnancy_category"] == "C"
        assert result["pediatric_age_threshold_months"] == 0
        assert result["is_approved_by_curator"] is True
        assert result["cdsco_schedule"] == "OTC"

    def test_preserves_clinical_text_fields(self):
        """GIVEN a CSV row with indications, side_effects, contraindications
        WHEN transform_row() is called
        THEN those fields MUST be preserved in the output.
        """
        mock_row = {
            "sku_id": "AZITH500",
            "brand_name": "Azithral 500",
            "generic_name": "Azithromycin",
            "indications": "Bacterial infections; Typhoid",
            "side_effects": "Nausea; Diarrhea",
            "contraindications": "Hepatic dysfunction",
            "price_inr": "120.00",
        }

        result = transform_row(mock_row)

        assert result["indications"] == "Bacterial infections; Typhoid"
        assert result["side_effects"] == "Nausea; Diarrhea"
        assert result["contraindications"] == "Hepatic dysfunction"


# =====================================================================
# TEST CLASS 2: transform_row — Resilience (Missing Keys)
# =====================================================================

class TestTransformRowResilience:
    """Verify transform_row() does NOT crash on missing or empty keys."""

    def test_handles_empty_dictionary(self):
        """GIVEN an empty dictionary (no keys at all)
        WHEN transform_row() is called
        THEN it MUST NOT raise an exception.
        """
        try:
            result = transform_row({})
            assert result["sku_id"] == ""
        except Exception:
            pytest.fail("transform_row() raised an exception on empty dict!")

    def test_handles_missing_sku_id(self):
        """GIVEN a row WITHOUT a sku_id key
        WHEN transform_row() is called
        THEN it MUST return empty string for sku_id instead of crashing.
        """
        mock_row = {
            "brand_name": "No ID Drug",
            "generic_name": "Mystery Molecule",
        }

        result = transform_row(mock_row)

        assert result["sku_id"] == ""

    def test_handles_missing_indications(self):
        """GIVEN a row WITHOUT clinical text fields
        WHEN transform_row() is called
        THEN it MUST return empty strings for those fields.
        """
        mock_row = {
            "sku_id": "MINI-001",
            "brand_name": "Minimal Drug",
        }

        result = transform_row(mock_row)

        assert result["indications"] == ""
        assert result["side_effects"] == ""
        assert result["contraindications"] == ""

    def test_handles_malformed_pediatric_age(self):
        """GIVEN a row with a non-numeric pediatric_age_threshold_months
        WHEN transform_row() is called
        THEN it MUST default to 0 instead of crashing.
        """
        mock_row = {
            "sku_id": "BADAGE-01",
            "pediatric_age_threshold_months": "not-a-number",
        }

        result = transform_row(mock_row)

        assert result["pediatric_age_threshold_months"] == 0

    def test_extracts_pregnancy_category_when_provided(self):
        """GIVEN a row with pregnancy_category = 'X'
        WHEN transform_row() is called
        THEN it MUST preserve that value instead of using the default.
        """
        mock_row = {
            "sku_id": "ISO-200",
            "pregnancy_category": "X",
        }

        result = transform_row(mock_row)

        assert result["pregnancy_category"] == "X"


# =====================================================================
# TEST CLASS 3: create_semantic_chunk
# =====================================================================

class TestCreateSemanticChunk:
    """Verify create_semantic_chunk() formats clinical text correctly."""

    def test_returns_string(self):
        """GIVEN a transformed row dictionary
        WHEN create_semantic_chunk() is called
        THEN it MUST return a string.
        """
        transformed = {
            "sku_id": "PAN40",
            "brand_name": "Pan 40",
            "generic_name": "Pantoprazole",
            "indications": "GERD; Acidity",
            "side_effects": "Headache; Nausea",
            "contraindications": "Severe liver disease",
            "price_inr": "135.00",
        }

        chunk = create_semantic_chunk(transformed)

        assert isinstance(chunk, str)
        assert len(chunk) > 0

    def test_contains_sku_and_brand(self):
        """GIVEN a transformed row
        WHEN create_semantic_chunk() is called
        THEN the output MUST contain the SKU and brand name.
        """
        transformed = {
            "sku_id": "ALLEGRA120",
            "brand_name": "Allegra 120",
            "generic_name": "Fexofenadine",
            "indications": "Allergic rhinitis",
            "side_effects": "Drowsiness",
            "contraindications": "Renal impairment",
            "price_inr": "180.00",
        }

        chunk = create_semantic_chunk(transformed)

        assert "ALLEGRA120" in chunk
        assert "Allegra 120" in chunk

    def test_semicolons_replaced_with_commas(self):
        """GIVEN indications with semicolons
        WHEN create_semantic_chunk() is called
        THEN semicolons MUST be replaced with commas for readability.
        """
        transformed = {
            "sku_id": "MULTI-01",
            "brand_name": "Multi Drug",
            "generic_name": "Multimum",
            "indications": "Fever; Pain; Inflammation",
            "side_effects": "Dizziness; Rash",
            "contraindications": "Asthma; Pregnancy",
            "price_inr": "50.00",
        }

        chunk = create_semantic_chunk(transformed)

        assert "," in chunk
        assert ";" not in chunk  # All semicolons replaced

    def test_handles_minimal_data(self):
        """GIVEN a transformed row with only sku_id
        WHEN create_semantic_chunk() is called
        THEN it MUST return a string containing at least the SKU.
        """
        transformed = {
            "sku_id": "MINI-002",
        }

        chunk = create_semantic_chunk(transformed)

        assert "MINI-002" in chunk

    def test_includes_price_when_present(self):
        """GIVEN a transformed row with a price
        WHEN create_semantic_chunk() is called
        THEN the price MUST appear in the output.
        """
        transformed = {
            "sku_id": "PRICE-01",
            "price_inr": "99.50",
        }

        chunk = create_semantic_chunk(transformed)

        assert "99.50" in chunk
        assert "INR" in chunk
