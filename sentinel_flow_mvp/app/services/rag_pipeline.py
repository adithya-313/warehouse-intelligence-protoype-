"""
RAG Pipeline with Adaptive Routing (Traffic Cop).

Beginner Note: This file decides whether a user's question needs the expensive
AI (Gemini) or can be answered instantly from the database. We call this
"Adaptive Routing" because we route each query to the cheapest channel that
can answer it correctly.

Think of it as a traffic cop at an intersection:
  - If the driver asks "What's the price?" → point them to the database (fast, free).
  - If the driver asks "Is this safe for a pregnant patient?" → point them to Gemini (slow, costly).
"""

import logging
from sqlalchemy.orm import Session
from app.core.config import get_application_settings
# Lazy import: execute_clinical_search is imported inside the function
# to avoid loading sentence_transformers (and its heavy torch/torchaudio
# dependencies) at module level. This keeps the module importable even
# when the full ML stack is not available.
# from app.services.semantic_search import execute_clinical_search
from app.infrastructure.models import MedicationBatchModel

logger = logging.getLogger(__name__)


# =====================================================================
# ADAPTIVE ROUTING: THE TRAFFIC COP
# =====================================================================
# This function acts as a middleware router. It inspects the user's query
# BEFORE deciding whether to call the expensive Gemini API or query the
# database directly.
#
# Why do we need this?
#   - Every call to Gemini costs money (even if it's just $0.01 per call).
#   - Many pharmacy questions are simple database lookups (e.g., "What is
#     the MRP?", "How many units in stock?").
#   - Calling Gemini for these simple questions is a waste of money AND
#     adds 2-3 seconds of latency.
#
# The solution: Check for objective keywords first. If found, answer from
# the database instantly (0 latency, $0 cost). Only fall through to Gemini
# for complex clinical questions that require real AI reasoning.

# The list of keywords that indicate an objective, fact-based question.
# These are questions that can be answered by simply querying the database
# without any AI reasoning.
OBJECTIVE_KEYWORDS_LIST = [
    "mrp",
    "price",
    "stock",
    "quantity",
    "available",
    "cost",
    "expiry",
]


def route_and_process_query(
    db: Session,
    query: str,
    sku_id: str = None
) -> dict:
    """
    Route a query to either the database (for objective questions) or
    Gemini RAG (for clinical/subjective questions).

    Parameters:
        db: Active database session.
        query: The user's natural language question.
        sku_id: Optional SKU identifier if the frontend knows which
                medication the user is asking about.

    Returns:
        dict with keys "answer" (str) and "context_used" (list), matching
        the same format as generate_clinical_response() so the caller
        doesn't need to know which route was taken.
    """
    # =====================================================================
    # STEP 1: CHECK IF THIS IS AN OBJECTIVE DATABASE QUERY
    # =====================================================================
    # We convert the query to lowercase so that "MRP" matches "mrp" and
    # "Price" matches "price". Case-insensitive matching is critical for
    # real-world use because pharmacists type in all sorts of ways.
    query_lowercase = query.lower()

    # Check if any of the objective keywords appear in the user's query.
    # We use a simple loop (not a one-liner) so a junior developer can
    # clearly see the logic.
    is_pricing_query = False
    for keyword in OBJECTIVE_KEYWORDS_LIST:
        if keyword in query_lowercase:
            is_pricing_query = True
            logger.info(
                f"Adaptive Router: Detected objective keyword '{keyword}' "
                f"in query. Will route to database."
            )
            break

    # =====================================================================
    # STEP 2: ROUTE TO DATABASE (if objective query AND we have a SKU)
    # =====================================================================
    # Beginner Note: We need sku_id to answer objective queries because
    # "what's the price?" is meaningless without knowing WHICH medication
    # the user is asking about. If the frontend didn't provide sku_id, we
    # fall through to Gemini which can infer context from the query text.
    if is_pricing_query and sku_id is not None:
        # Query all batches of this medication from the database.
        # We fetch all batches because the user might want aggregate info
        # like total stock (sum of all batches) or earliest expiry.
        medication_batches = db.query(MedicationBatchModel).filter(
            MedicationBatchModel.sku_id == sku_id
        ).order_by(
            MedicationBatchModel.expiry_date.asc()
        ).all()

        if medication_batches:
            # Calculate aggregate values across all batches
            total_stock = sum(
                batch.available_quantity for batch in medication_batches
            )
            lowest_price = min(
                batch.max_retail_price for batch in medication_batches
            )
            earliest_expiry = medication_batches[0].expiry_date

            # Format a natural-sounding answer string.
            # We include the batch-level details so the pharmacist has
            # full visibility into each batch's status.
            formatted_answer = (
                f"SKU {sku_id} — "
                f"MRP: ₹{lowest_price:.2f}, "
                f"Total Stock: {total_stock} units, "
                f"Earliest Expiry: {earliest_expiry.isoformat()}. "
            )

            logger.info(
                f"Adaptive Router: Answered objective query from database. "
                f"SKU={sku_id}, Stock={total_stock}, MRP=₹{lowest_price}"
            )

            return {
                "answer": formatted_answer,
                "context_used": []
            }

        else:
            # No batches found in the database for this SKU.
            return {
                "answer": (
                    f"No inventory records found for SKU '{sku_id}'. "
                    "Please verify the SKU or check inventory master."
                ),
                "context_used": []
            }

    # =====================================================================
    # STEP 3: FALL-THROUGH TO GEMINI RAG (Clinical/Subjective questions)
    # =====================================================================
    # If we reached this point, one of two things is true:
    #   1. The query is a clinical/subjective question (e.g., "Is this safe
    #      for a patient with liver disease?") — this REQUIRES AI reasoning.
    #   2. The query matches objective keywords but no sku_id was provided
    #      — we send it to Gemini so it can try to infer the medication
    #      from the context of the conversation.
    #
    # In both cases, we delegate to the existing generate_clinical_response()
    # function which handles the full Retrieval-Augmented Generation pipeline.

    logger.info(
        "Adaptive Router: No objective database match found. "
        "Routing to Gemini RAG pipeline."
    )

    return generate_clinical_response(
        db=db,
        query=query,
        sku_id=sku_id
    )


def generate_clinical_response(
    db: Session,
    query: str,
    sku_id: str = None
) -> dict:
    """
    Retrieval-Augmented Generation (RAG) Pipeline.
    1. Retrieves relevant clinical context using PubMedBERT vector search.
    2. Feeds the context to Google Gemini with a strict 'Do Not Hallucinate' prompt.
    """

    # STEP 0: DYNAMIC API KEY CONFIGURATION
    # We fetch the application settings at runtime instead of module load time.
    # This guarantees we have the latest environment variables loaded safely.
    # Lazy import: google.generativeai is only imported when RAG is actually used.
    import google.generativeai as genai
    settings = get_application_settings()
    if settings.GEMINI_API_KEY:
        genai.configure(api_key=settings.GEMINI_API_KEY)
    else:
        logger.warning("GEMINI_API_KEY is missing. RAG pipeline will fail if called.")

    # STEP 1: RETRIEVAL (Get the facts from our database)
    # We query the vector database for the top 3 most relevant clinical guidelines.
    # Lazy import: Only load sentence_transformers when clinical RAG is actually needed.
    from app.services.semantic_search import execute_clinical_search
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
        # We use gemini-1.5-flash for high speed and low latency (fixed invalid model name)
        model = genai.GenerativeModel('gemini-1.5-flash')

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
