import logging
import google.generativeai as genai
from sqlalchemy.orm import Session
from app.core.config import get_application_settings
from app.services.semantic_search import execute_clinical_search

logger = logging.getLogger(__name__)

# Initialize Gemini Configuration
settings = get_application_settings()
if settings.GEMINI_API_KEY:
    genai.configure(api_key=settings.GEMINI_API_KEY)
else:
    logger.warning("GEMINI_API_KEY is missing. RAG pipeline will fail if called.")

def generate_clinical_response(db: Session, query: str, sku_id: str = None) -> dict:
    """
    Retrieval-Augmented Generation (RAG) Pipeline.
    1. Retrieves relevant clinical context using PubMedBERT vector search.
    2. Feeds the context to Google Gemini with a strict 'Do Not Hallucinate' prompt.
    """
    
    # STEP 1: RETRIEVAL (Get the facts from our database)
    search_results = execute_clinical_search(db=db, query=query, sku_id=sku_id, top_k=3)
    
    # If the safety breaker tripped (no high-confidence results), degrade gracefully.
    if search_results.get("safety_warning"):
        return {
            "answer": search_results["safety_warning"],
            "context_used": []
        }
        
    context_items = search_results["results"]
    
    # STEP 2: FORMAT CONTEXT
    # Combine the retrieved text blocks into a single string for the AI to read.
    context_blocks = "\n\n".join([f"- {item['content']}" for item in context_items])
    
    # STEP 3: PROMPT ENGINEERING (Strict Constraints)
    prompt = f"""You are a strict clinical safety assistant for a pharmacy.
Your job is to answer the user's query using ONLY the provided clinical context.

RULES:
1. Do NOT hallucinate or use outside medical knowledge.
2. If the provided context does not contain the answer, reply EXACTLY with: "INSUFFICIENT CLINICAL DATA. CONSULT PHARMACIST."
3. Keep the answer concise, professional, and direct.

CLINICAL CONTEXT:
{context_blocks}

USER QUERY:
{query}
"""

    # STEP 4: GENERATION (Call Gemini)
    try:
        # We use gemini-3.5-flash for high speed and low latency
        model = genai.GenerativeModel('gemini-3.5-flash')
        
        # Temperature = 0.0 forces the AI to be deterministic and analytical, not creative.
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=0.0)
        )
        
        return {
            "answer": response.text.strip(),
            "context_used": context_items
        }
        
    except Exception as e:
        logger.error(f"Gemini API generation failed: {str(e)}")
        return {
            "answer": "SYSTEM ERROR: AI Generation failed. Please consult a pharmacist.",
            "context_used": context_items
        }
