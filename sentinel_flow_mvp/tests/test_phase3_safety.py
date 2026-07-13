"""
Phase 3 — Rule Engine & Structured Narrator Tests.

Beginner Note:
    This test file validates THREE things:
    1. The ClinicalSafetyJudge (Rule Engine) makes correct deterministic
       decisions for pregnancy contraindications and pediatric age limits.
    2. The ClinicalNarrativeSchema correctly validates structured JSON.
    3. The enriched records flow works (medication safety data is merged
       into clinical search results).

    We test the Judge in ISOLATION — no database, no Gemini API.
    This is the whole point of the Rule Engine: it should work perfectly
    with just a dict of intents and a list of records.
"""

import json
import pytest
from pydantic import ValidationError

# =====================================================================
# Import the modules we are testing
# =====================================================================
# Beginner Note: We import from the actual source files. No mocks are
# needed for the Rule Engine because it is 100% deterministic — it
# only inspects Python dicts and returns Python dicts. No database,
# no network, no AI calls.

from app.services.rule_engine import ClinicalSafetyJudge
from app.domain.schemas import ClinicalNarrativeSchema


# =====================================================================
# FIXTURES: Reusable test data
# =====================================================================
# Beginner Note: Fixtures are pytest's way of creating reusable test
# objects. We define our mock records and intents here so each test
# function can request exactly what it needs without repeating code.

@pytest.fixture
def judge():
    """Create a fresh ClinicalSafetyJudge for each test."""
    return ClinicalSafetyJudge()


@pytest.fixture
def pregnancy_intents():
    """Intents dict simulating a pregnant patient asking about a drug."""
    return {"pregnancy": True, "pediatric": False, "substitute": False}


@pytest.fixture
def pediatric_intents():
    """Intents dict simulating a pediatric patient question."""
    return {"pregnancy": False, "pediatric": True, "substitute": False}


@pytest.fixture
def no_special_intents():
    """Intents dict with no special safety concerns."""
    return {"pregnancy": False, "pediatric": False, "substitute": False}


@pytest.fixture
def category_x_record():
    """
    A mock retrieved record with pregnancy_category = 'X'.
    
    Category X means "DO NOT DISPENSE to a pregnant patient."
    This should trigger the pregnancy contraindication rule.
    """
    return {
        "sku_id": "ISO-200",
        "content": "Isotretinoin is absolutely contraindicated in pregnancy.",
        "pregnancy_category": "X",
        "pediatric_age_threshold_months": None,
    }


@pytest.fixture
def category_d_record():
    """
    A mock retrieved record with pregnancy_category = 'D'.
    
    Category D means "Positive evidence of human fetal risk."
    Our Rule Engine treats D the same as X — BLOCK by default.
    """
    return {
        "sku_id": "VAL-10",
        "content": "Valproate carries significant risk of congenital malformations.",
        "pregnancy_category": "D",
        "pediatric_age_threshold_months": None,
    }


@pytest.fixture
def category_b_record():
    """
    A mock retrieved record with pregnancy_category = 'B'.
    
    Category B means "No evidence of risk in humans."
    This should NOT trigger the pregnancy rule — the drug is safe.
    """
    return {
        "sku_id": "AMOXI-500",
        "content": "Amoxicillin is generally considered safe in pregnancy.",
        "pregnancy_category": "B",
        "pediatric_age_threshold_months": None,
    }


@pytest.fixture
def age_restricted_record():
    """
    A mock record with a pediatric age threshold of 24 months.
    
    This means "Do not dispense to children under 2 years old."
    With the default patient_age = 0 months, this should trigger
    the pediatric age violation rule.
    """
    return {
        "sku_id": "DOLO-650",
        "content": "Paracetamol should not be given to infants under 2 years.",
        "pregnancy_category": None,
        "pediatric_age_threshold_months": 24,
    }


@pytest.fixture
def safe_record():
    """A mock record with no safety restrictions at all."""
    return {
        "sku_id": "PARA-500",
        "content": "Paracetamol 500mg is safe for general use.",
        "pregnancy_category": None,
        "pediatric_age_threshold_months": None,
    }


# =====================================================================
# TEST CLASS 1: ClinicalSafetyJudge — Pregnancy Safety
# =====================================================================
# These tests verify that the Judge correctly blocks Category X and D
# drugs when the pregnancy intent is True, and allows Category B drugs.

class TestPregnancySafety:
    """Verify the Judge's pregnancy contraindication logic."""

    def test_blocks_category_x_drug(self, judge, pregnancy_intents, category_x_record):
        """
        GIVEN a pregnant patient (pregnancy intent = True)
        AND  a drug with pregnancy_category = "X"
        THEN the Judge MUST return is_safe = False
        AND  lock_reason MUST be "CRITICAL_PREGNANCY_CONTRAINDICATION"
        """
        verdict = judge.evaluate_safety(
            intents=pregnancy_intents,
            retrieved_records=[category_x_record],
        )

        assert verdict["is_safe"] is False, (
            "Category X drug must be blocked for pregnant patients."
        )
        assert verdict["lock_reason"] == "CRITICAL_PREGNANCY_CONTRAINDICATION", (
            f"Expected CRITICAL_PREGNANCY_CONTRAINDICATION, "
            f"got {verdict['lock_reason']}"
        )
        assert verdict["triggered_rule"] == "Pregnancy Category X/D Check", (
            f"Expected 'Pregnancy Category X/D Check' rule trigger, "
            f"got {verdict['triggered_rule']}"
        )

    def test_blocks_category_d_drug(self, judge, pregnancy_intents, category_d_record):
        """
        GIVEN a pregnant patient
        AND  a drug with pregnancy_category = "D"
        THEN the Judge MUST return is_safe = False
        """
        verdict = judge.evaluate_safety(
            intents=pregnancy_intents,
            retrieved_records=[category_d_record],
        )

        assert verdict["is_safe"] is False, (
            "Category D drug must be blocked for pregnant patients."
        )
        assert verdict["lock_reason"] == "CRITICAL_PREGNANCY_CONTRAINDICATION"

    def test_allows_category_b_drug(self, judge, pregnancy_intents, category_b_record):
        """
        GIVEN a pregnant patient
        AND  a drug with pregnancy_category = "B" (safe)
        THEN the Judge MUST return is_safe = True
        """
        verdict = judge.evaluate_safety(
            intents=pregnancy_intents,
            retrieved_records=[category_b_record],
        )

        assert verdict["is_safe"] is True, (
            "Category B drug must be allowed for pregnant patients."
        )
        assert verdict["lock_reason"] is None

    def test_allows_when_no_pregnancy_intent(self, judge, category_x_record):
        """
        GIVEN NO pregnancy intent (patient is not pregnant)
        AND  a Category X drug
        THEN the Judge MUST return is_safe = True
        (because pregnancy check is skipped when intent is absent)
        """
        verdict = judge.evaluate_safety(
            intents={"pregnancy": False},
            retrieved_records=[category_x_record],
        )

        assert verdict["is_safe"] is True, (
            "Category X drug must be allowed when pregnancy intent is absent."
        )

    def test_allows_pregnancy_when_category_is_none(self, judge, pregnancy_intents, safe_record):
        """
        GIVEN a pregnant patient
        AND  a drug with pregnancy_category = None (unclassified)
        THEN the Judge MUST return is_safe = True
        (we do NOT block unclassified drugs — absence of data is not evidence of harm)
        """
        verdict = judge.evaluate_safety(
            intents=pregnancy_intents,
            retrieved_records=[safe_record],
        )

        assert verdict["is_safe"] is True, (
            "Drugs with null pregnancy category must not be blocked."
        )


# =====================================================================
# TEST CLASS 2: ClinicalSafetyJudge — Pediatric Safety
# =====================================================================

class TestPediatricSafety:
    """Verify the Judge's pediatric age threshold logic."""

    def test_blocks_age_restricted_drug(self, judge, pediatric_intents, age_restricted_record):
        """
        GIVEN a pediatric patient (pediatric intent = True)
        AND  a drug with pediatric_age_threshold_months = 24
        AND  no patient_age provided (defaults to 0 = newborn)
        THEN the Judge MUST return is_safe = False
        AND  lock_reason MUST be "PEDIATRIC_AGE_VIOLATION"
        """
        verdict = judge.evaluate_safety(
            intents=pediatric_intents,
            retrieved_records=[age_restricted_record],
        )

        assert verdict["is_safe"] is False, (
            "Age-restricted drug must be blocked for pediatric patients."
        )
        assert verdict["lock_reason"] == "PEDIATRIC_AGE_VIOLATION", (
            f"Expected PEDIATRIC_AGE_VIOLATION, got {verdict['lock_reason']}"
        )
        assert verdict["triggered_rule"] == "Pediatric Age Threshold Check"

    def test_allows_age_restricted_when_patient_is_old_enough(self, judge, age_restricted_record):
        """
        GIVEN a pediatric intent WITH patient_age_months = 36 (3 years old)
        AND  a drug with pediatric_age_threshold_months = 24
        THEN the Judge MUST return is_safe = True
        (the patient is old enough to receive this medication)
        """
        verdict = judge.evaluate_safety(
            intents={"pregnancy": False, "pediatric": True, "patient_age_months": 36},
            retrieved_records=[age_restricted_record],
        )

        assert verdict["is_safe"] is True, (
            "Drug must be allowed when patient age exceeds threshold."
        )

    def test_allows_when_no_age_threshold(self, judge, pediatric_intents, safe_record):
        """
        GIVEN a pediatric patient
        AND  a drug with pediatric_age_threshold_months = None
        THEN the Judge MUST return is_safe = True
        """
        verdict = judge.evaluate_safety(
            intents=pediatric_intents,
            retrieved_records=[safe_record],
        )

        assert verdict["is_safe"] is True

    def test_allows_when_no_pediatric_intent(self, judge, age_restricted_record):
        """
        GIVEN NO pediatric intent
        AND  a drug with pediatric_age_threshold_months = 24
        THEN the Judge MUST return is_safe = True
        """
        verdict = judge.evaluate_safety(
            intents={"pregnancy": False, "pediatric": False},
            retrieved_records=[age_restricted_record],
        )

        assert verdict["is_safe"] is True


# =====================================================================
# TEST CLASS 3: ClinicalSafetyJudge — Multiple Records Handling
# =====================================================================

class TestMultipleRecords:
    """Verify the Judge handles multiple records correctly."""

    def test_blocks_if_any_record_triggers_pregnancy(self, judge, pregnancy_intents):
        """
        GIVEN a mixed list of records (one safe, one Category X)
        AND  pregnancy intent is True
        THEN the Judge MUST block because at least one record is unsafe
        """
        records = [
            {"sku_id": "SAFE-01", "pregnancy_category": "B"},
            {"sku_id": "UNSAFE-01", "pregnancy_category": "X"},
        ]

        verdict = judge.evaluate_safety(intents=pregnancy_intents, retrieved_records=records)

        assert verdict["is_safe"] is False, (
            "If ANY record has Category X, the entire transaction must be blocked."
        )

    def test_allows_if_all_records_are_safe(self, judge, pregnancy_intents):
        """
        GIVEN a list of records ALL with safe pregnancy categories
        THEN the Judge must return is_safe = True
        """
        records = [
            {"sku_id": "A", "pregnancy_category": "A"},
            {"sku_id": "B", "pregnancy_category": "B"},
            {"sku_id": "C", "pregnancy_category": "C"},
        ]

        verdict = judge.evaluate_safety(intents=pregnancy_intents, retrieved_records=records)

        assert verdict["is_safe"] is True


# =====================================================================
# TEST CLASS 4: ClinicalNarrativeSchema Validation
# =====================================================================
# These tests verify the Pydantic model that validates Gemini's JSON output.

class TestClinicalNarrativeSchema:
    """Verify ClinicalNarrativeSchema correctly validates structured JSON."""

    def test_valid_safe_narrative(self):
        """
        GIVEN a valid JSON dict with is_safe_to_dispense=True
        THEN ClinicalNarrativeSchema must parse it without error
        """
        data = {
            "is_safe_to_dispense": True,
            "narrative": "This medication is safe for the patient.",
            "system_lock_reason": None,
            "citations": ["CDSCO Guideline 2024: Paracetamol Safety"],
        }
        narrative = ClinicalNarrativeSchema(**data)

        assert narrative.is_safe_to_dispense is True
        assert narrative.narrative == "This medication is safe for the patient."
        assert narrative.system_lock_reason is None
        assert len(narrative.citations) == 1

    def test_valid_unsafe_narrative_with_lock_reason(self):
        """
        GIVEN a valid JSON dict with is_safe_to_dispense=False
        AND  a system_lock_reason
        THEN ClinicalNarrativeSchema must parse it correctly
        """
        data = {
            "is_safe_to_dispense": False,
            "narrative": "This medication is contraindicated in pregnancy.",
            "system_lock_reason": "CRITICAL_PREGNANCY_CONTRAINDICATION",
            "citations": [],
        }
        narrative = ClinicalNarrativeSchema(**data)

        assert narrative.is_safe_to_dispense is False
        assert narrative.system_lock_reason == "CRITICAL_PREGNANCY_CONTRAINDICATION"
        assert narrative.citations == []

    def test_rejects_missing_required_field(self):
        """
        GIVEN a JSON dict MISSING the 'narrative' field
        THEN ClinicalNarrativeSchema MUST raise ValidationError
        """
        data = {
            "is_safe_to_dispense": True,
            # "narrative" is missing
            "system_lock_reason": None,
            "citations": [],
        }
        with pytest.raises(ValidationError):
            ClinicalNarrativeSchema(**data)

    def test_rejects_wrong_type_for_boolean(self):
        """
        GIVEN a JSON dict where is_safe_to_dispense is a string instead of bool
        THEN ClinicalNarrativeSchema MUST raise ValidationError
        """
        data = {
            "is_safe_to_dispense": "yes",  # wrong type — should be bool
            "narrative": "Some narrative.",
            "system_lock_reason": None,
            "citations": [],
        }
        with pytest.raises(ValidationError):
            ClinicalNarrativeSchema(**data)


# =====================================================================
# TEST CLASS 5: ClinicalSafetyJudge — Statelessness
# =====================================================================

class TestJudgeStatelessness:
    """Verify the Judge has no internal state between calls."""

    def test_multiple_calls_produce_same_result(self, judge, pregnancy_intents, category_x_record):
        """
        GIVEN the same inputs
        THEN calling evaluate_safety twice MUST produce identical results
        """
        result1 = judge.evaluate_safety(pregnancy_intents, [category_x_record])
        result2 = judge.evaluate_safety(pregnancy_intents, [category_x_record])

        assert result1 == result2, (
            "Judge must be stateless — same inputs must produce same outputs."
        )

    def test_consecutive_calls_dont_interfere(self, judge):
        """
        GIVEN two different input sets
        THEN consecutive calls must not interfere with each other
        """
        # First call: unsafe
        unsafe_result = judge.evaluate_safety(
            intents={"pregnancy": True},
            retrieved_records=[{"sku_id": "X", "pregnancy_category": "X"}],
        )

        # Second call: safe
        safe_result = judge.evaluate_safety(
            intents={"pregnancy": False},
            retrieved_records=[{"sku_id": "X", "pregnancy_category": "X"}],
        )

        assert unsafe_result["is_safe"] is False
        assert safe_result["is_safe"] is True
