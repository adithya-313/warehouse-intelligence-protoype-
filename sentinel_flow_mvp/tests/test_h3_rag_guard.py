import pytest
from unittest.mock import patch, MagicMock
from app.services.rag_pipeline import generate_clinical_response, extract_known_entities

@pytest.fixture(autouse=True)
def _mock_genai_modules():
    genai_mock = MagicMock()
    # Provide a default mock response for any generation calls
    genai_mock.Client.return_value.models.generate_content.return_value = MagicMock(
        text='{"question_type": "general_info", "is_safe_to_dispense": true, "narrative": "test", "system_lock_reason": null, "citations": []}'
    )
    with patch.dict("sys.modules", {
        "google.genai": genai_mock,
        "google.genai.types": MagicMock(),
        "app.services.semantic_search": MagicMock()
    }):
        yield genai_mock

@pytest.mark.asyncio
async def test_rag_guard_multiple_distinct_skus():
    """
    Unit test: extract_known_entities() returns records for 2 distinct SKUs -> 
    confirm the function/caller returns disambiguate with both SKUs listed, 
    and confirm generation is never called.
    """
    mock_db = MagicMock()
    
    with patch("app.services.rag_pipeline.extract_known_entities") as mock_extract:
        # Simulate returning multiple distinct drugs
        mock_extract.return_value = {
            "status": "disambiguate", 
            "choices": ["GENERIC_REF_AMOXYCILLIN", "GENERIC_REF_AMPICILLIN"]
        }
        
        with patch("app.services.semantic_search.execute_clinical_search") as mock_search:
            result = await generate_clinical_response(
                db=mock_db,
                query="what is amoxicillin and ampicillin used for"
            )
            
            assert result == {
                "status": "disambiguate", 
                "choices": ["GENERIC_REF_AMOXYCILLIN", "GENERIC_REF_AMPICILLIN"]
            }
            # Confirm generation (search/LLM) is NEVER called
            mock_search.assert_not_called()

@pytest.mark.asyncio
async def test_rag_guard_single_distinct_sku():
    """
    Unit test: records for 1 distinct SKU (even with duplicate rows) -> 
    confirm generation still proceeds normally, unchanged from today.
    """
    mock_db = MagicMock()
    
    with patch("app.services.rag_pipeline.extract_known_entities") as mock_extract:
        # Simulate returning 1 distinct drug (duplicate rows)
        mock_extract.return_value = [
            {"sku_id": "GENERIC_REF_AMOXYCILLIN", "content": "chunk 1", "confidence_score": 1.0, "metadata_payload": {}},
            {"sku_id": "GENERIC_REF_AMOXYCILLIN", "content": "chunk 2", "confidence_score": 1.0, "metadata_payload": {}}
        ]
        
        with patch("app.services.semantic_search.execute_clinical_search") as mock_search, \
             patch("app.services.rag_pipeline.ClinicalSafetyJudge") as mock_judge, \
             patch("app.services.rag_pipeline._gemini_circuit_breaker_instance") as mock_cb:
            
            # Setup mocks to prevent actual API calls during test
            mock_search.return_value = {"results": []}
            mock_judge_instance = mock_judge.return_value
            mock_judge_instance.evaluate_safety.return_value = {"is_safe": True, "reason": None}
            
            result = await generate_clinical_response(
                db=mock_db,
                query="what is amoxicillin used for"
            )
            
            # Generation SHOULD be called
            mock_search.assert_called_once()
            assert "answer" in result
            assert result.get("status") != "disambiguate"
