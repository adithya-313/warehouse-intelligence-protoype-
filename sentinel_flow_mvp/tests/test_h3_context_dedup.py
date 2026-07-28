import pytest
from unittest.mock import patch, MagicMock
from app.services.rag_pipeline import generate_clinical_response

@pytest.fixture(autouse=True)
def _mock_genai_modules():
    genai_mock = MagicMock()
    genai_mock.Client.return_value.models.generate_content.return_value = MagicMock(
        text='{"question_type": "general_info", "is_safe_to_dispense": true, "narrative": "test", "system_lock_reason": null, "citations": []}'
    )
    with patch.dict("sys.modules", {
        "google.genai": genai_mock,
        "google.genai.types": MagicMock(),
        "app.services.semantic_search": MagicMock(),
    }):
        yield genai_mock

@pytest.mark.asyncio
async def test_dedup_identical_records():
    mock_db = MagicMock()
    # Mock search to return PAN40
    search_mock = {"results": [{"sku_id": "PAN40", "content": "full text", "confidence_score": 0.9, "metadata_payload": {}}], "safety_warning": None}
    # Mock extract to return PAN40 exactly the same
    extract_mock = [{"sku_id": "PAN40", "content": "full text", "confidence_score": 1.0, "metadata_payload": {}}]
    
    with patch("app.services.semantic_search.execute_clinical_search", return_value=search_mock), \
         patch("app.services.rag_pipeline.extract_known_entities", return_value=extract_mock), \
         patch("app.services.rag_pipeline.ClinicalSafetyJudge") as mock_judge, \
         patch("app.services.rag_pipeline.get_optimal_fefo_batch", return_value=None), \
         patch("app.services.rag_pipeline._gemini_circuit_breaker_instance"):
         
        mock_judge.return_value.evaluate_safety.return_value = {"is_safe": True, "reason": None}
        
        result = await generate_clinical_response(mock_db, "tell me about pan40")
        assert len(result["context_used"]) == 1
        assert result["context_used"][0]["sku_id"] == "PAN40"

@pytest.mark.asyncio
async def test_dedup_different_skus():
    mock_db = MagicMock()
    # Mock search to return PAN40
    search_mock = {"results": [{"sku_id": "PAN40", "content": "pan40 text", "confidence_score": 0.9, "metadata_payload": {}}], "safety_warning": None}
    # Mock extract to return DOLO650
    extract_mock = [{"sku_id": "DOLO650", "content": "dolo text", "confidence_score": 1.0, "metadata_payload": {}}]
    
    with patch("app.services.semantic_search.execute_clinical_search", return_value=search_mock), \
         patch("app.services.rag_pipeline.extract_known_entities", return_value=extract_mock), \
         patch("app.services.rag_pipeline.ClinicalSafetyJudge") as mock_judge, \
         patch("app.services.rag_pipeline.get_optimal_fefo_batch", return_value=None), \
         patch("app.services.rag_pipeline._gemini_circuit_breaker_instance"):
         
        mock_judge.return_value.evaluate_safety.return_value = {"is_safe": True, "reason": None}
        
        result = await generate_clinical_response(mock_db, "tell me about pan40 and dolo650")
        assert len(result["context_used"]) == 2
        skus = {c["sku_id"] for c in result["context_used"]}
        assert skus == {"PAN40", "DOLO650"}

@pytest.mark.asyncio
async def test_dedup_completeness_preference():
    mock_db = MagicMock()
    # Mock search to return PAN40 incomplete
    search_mock = {"results": [{"sku_id": "PAN40", "content": "short", "confidence_score": 0.9, "metadata_payload": {}}], "safety_warning": None}
    # Mock extract to return PAN40 complete
    extract_mock = [{"sku_id": "PAN40", "content": "longer complete text", "confidence_score": 1.0, "metadata_payload": {}}]
    
    with patch("app.services.semantic_search.execute_clinical_search", return_value=search_mock), \
         patch("app.services.rag_pipeline.extract_known_entities", return_value=extract_mock), \
         patch("app.services.rag_pipeline.ClinicalSafetyJudge") as mock_judge, \
         patch("app.services.rag_pipeline.get_optimal_fefo_batch", return_value=None), \
         patch("app.services.rag_pipeline._gemini_circuit_breaker_instance"):
         
        mock_judge.return_value.evaluate_safety.return_value = {"is_safe": True, "reason": None}
        
        result = await generate_clinical_response(mock_db, "tell me about pan40")
        assert len(result["context_used"]) == 1
        assert result["context_used"][0]["sku_id"] == "PAN40"
        assert result["context_used"][0]["content"] == "longer complete text"
