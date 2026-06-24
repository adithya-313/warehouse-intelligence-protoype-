import sys
import traceback

def run_validation():
    print("Starting System Validation...")
    try:
        # 1. Validate Configuration
        from app.core.config import ApplicationSettings
        fields = ApplicationSettings.__fields__ if hasattr(ApplicationSettings, '__fields__') else ApplicationSettings.model_fields
        assert "GEMINI_API_KEY" in fields, "GEMINI_API_KEY missing from ApplicationSettings"
        print("[OK] Configuration Schema Validated.")

        # 2. Validate Schemas
        from app.domain.schemas import RAGQueryRequest, RAGQueryResponse
        assert "query" in RAGQueryRequest.model_fields, "RAGQueryRequest missing 'query'"
        print("[OK] Pydantic Schemas Validated.")

        # 3. Validate Router Endpoints
        from app.api.v1.knowledge_base import router
        routes = [route.path for route in router.routes]
        assert "/ingest" in routes, "Missing /ingest endpoint"
        assert "/search" in routes, "Missing /search endpoint"
        assert "/ask" in routes, "Missing /ask endpoint"
        print("[OK] API Topology Validated.")

        # 4. Validate Model Upgrade
        with open("app/services/rag_pipeline.py", "r") as f:
            content = f.read()
            assert "gemini-3.5-flash" in content, "Model not upgraded to gemini-3.5-flash"
        print("[OK] LLM Model Version Validated.")

        print("\nSYSTEM VALIDATION PASSED. NO ARCHITECTURAL FRACTURES DETECTED.")
        sys.exit(0)

    except Exception as e:
        print("\n[CRITICAL FAILURE] Validation caught an error:")
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    run_validation()
