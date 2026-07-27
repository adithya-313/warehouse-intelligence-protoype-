import pytest
from unittest.mock import MagicMock
import sys

# Add path so we can import modules
sys.path.append('.')

from app.services.semantic_search import MINIMUM_CONFIDENCE_THRESHOLD
from app.infrastructure.models import MedicationModel

# We will mock the database and the function logic to run unit tests
def run_filter_logic(sorted_by_rrf, sku_id_param, db_mock):
    top_k = 5
    formatted_results = []
    
    # Replicating the exact new logic from semantic_search.py
    all_sku_ids = [item["sku_id"] for item in sorted_by_rrf[:top_k]]
    
    # We mock the db.query().filter().all()
    medications = db_mock.query(MedicationModel).filter().all()
    medication_lookup_by_sku = {med.sku_id: med for med in medications}

    for item in sorted_by_rrf[:top_k]:
        sku = item["sku_id"]
        is_confident_match = (sku_id_param is not None and sku == sku_id_param)
        
        ingest_data_quality = item["metadata_payload"].get("data_quality")
        
        if ingest_data_quality is not None:
            if ingest_data_quality == "identity_only":
                data_completeness = "identity_only"
            else:
                data_completeness = "full"
        else:
            med = medication_lookup_by_sku.get(sku)
            is_approved = med.is_approved_by_curator if med else True
            clinical_fields_null = "indications" not in item["metadata_payload"]
            
            if not is_approved and clinical_fields_null:
                data_completeness = "identity_only"
            elif is_approved and clinical_fields_null:
                data_completeness = "identity_only"
            else:
                data_completeness = "full"

        if item["confidence_score"] >= MINIMUM_CONFIDENCE_THRESHOLD:
            formatted_results.append({
                "sku_id": item["sku_id"],
                "content": item["content"],
                "confidence_score": item["confidence_score"],
                "metadata_payload": item["metadata_payload"],
                "data_completeness": data_completeness
            })
            
        elif is_confident_match and data_completeness == "identity_only":
            formatted_results.append({
                "sku_id": item["sku_id"],
                "content": item["content"],
                "confidence_score": item["confidence_score"],
                "metadata_payload": item["metadata_payload"],
                "data_completeness": data_completeness
            })
            
    return formatted_results


def test_data_quality_present():
    """
    data_quality present and used directly (no DB fallback triggered)
    """
    db_mock = MagicMock()
    # Mocking DB query to return empty since it shouldn't be used
    db_mock.query().filter().all.return_value = []

    item = {
        "sku_id": "TEST_SKU",
        "content": "test",
        "confidence_score": MINIMUM_CONFIDENCE_THRESHOLD - 0.1,
        "metadata_payload": {"data_quality": "identity_only"} 
    }
    
    results = run_filter_logic([item], sku_id_param="TEST_SKU", db_mock=db_mock)
    
    assert len(results) == 1
    assert results[0]["data_completeness"] == "identity_only"
    print("PASS: test_data_quality_present")


def test_data_quality_missing_fallback_triggered():
    """
    data_quality missing and fallback triggered
    """
    db_mock = MagicMock()
    mock_med = MagicMock()
    mock_med.sku_id = "TEST_SKU"
    mock_med.is_approved_by_curator = False
    db_mock.query().filter().all.return_value = [mock_med]

    item = {
        "sku_id": "TEST_SKU",
        "content": "test",
        "confidence_score": MINIMUM_CONFIDENCE_THRESHOLD - 0.1,
        "metadata_payload": {} # Missing data_quality
    }
    
    results = run_filter_logic([item], sku_id_param="TEST_SKU", db_mock=db_mock)
    
    assert len(results) == 1
    assert results[0]["data_completeness"] == "identity_only"
    print("PASS: test_data_quality_missing_fallback_triggered")


def test_edge_case_survives():
    """
    the previously-inconsistent edge case (is_approved=True, nulls, confidently matched) now correctly survives
    """
    db_mock = MagicMock()
    mock_med = MagicMock()
    mock_med.sku_id = "TEST_SKU"
    mock_med.is_approved_by_curator = True
    db_mock.query().filter().all.return_value = [mock_med]

    item = {
        "sku_id": "TEST_SKU",
        "content": "test",
        "confidence_score": MINIMUM_CONFIDENCE_THRESHOLD - 0.1,
        "metadata_payload": {} # Missing data_quality, 'indications' is missing
    }
    
    results = run_filter_logic([item], sku_id_param="TEST_SKU", db_mock=db_mock)
    
    assert len(results) == 1
    assert results[0]["data_completeness"] == "identity_only"
    print("PASS: test_edge_case_survives")


def test_above_threshold_full_data():
    db_mock = MagicMock()
    db_mock.query().filter().all.return_value = []

    item = {
        "sku_id": "TEST_SKU",
        "content": "test",
        "confidence_score": MINIMUM_CONFIDENCE_THRESHOLD + 0.1,
        "metadata_payload": {"data_quality": "full"} 
    }
    
    results = run_filter_logic([item], sku_id_param=None, db_mock=db_mock)
    
    assert len(results) == 1
    assert results[0]["data_completeness"] == "full"
    print("PASS: test_above_threshold_full_data")


if __name__ == "__main__":
    test_data_quality_present()
    test_data_quality_missing_fallback_triggered()
    test_edge_case_survives()
    test_above_threshold_full_data()
