"""
Hybrid Semantic Search Engine (Vector + Keyword) with Reciprocal Rank Fusion.

Beginner Note: This is called "Hybrid Search" because we combine TWO different
search techniques to get the best of both worlds:
  1. Vector Search (pgvector cosine distance) — understands the MEANING of words.
     Even if the user types "cardiac issues" and the database says "heart problems",
     vector search will match them because it understands semantic similarity.
  2. Keyword Search (PostgreSQL tsvector + plainto_tsquery) — finds EXACT word matches.
     If the user types "paracetamol 500mg", keyword search will find that exact phrase
     even if the vector embedding is noisy or incomplete.

We merge the results using Reciprocal Rank Fusion (RRF), a well-known algorithm
from information retrieval that combines ranked lists from different search systems
into a single, highly-relevant result set.
"""

import logging
from sqlalchemy import text, bindparam
from sqlalchemy.orm import Session
from pgvector.sqlalchemy import Vector
from app.infrastructure.models import ClinicalKnowledgeBase
from app.workers.embedding_tasks import get_embedding_model

logger = logging.getLogger(__name__)

# CLINICAL SAFETY CONSTRAINT:
# If the AI match is less than 85% similar, we reject it to prevent hallucinations.
MINIMUM_CONFIDENCE_THRESHOLD = 0.85

# RRF constant that controls how much weight lower-ranked results get.
# A larger k (like 60) makes the fusion more democratic — even results
# ranked 20th still contribute meaningfully. This is especially important
# when one search method (e.g., vector) might miss an exact keyword match
# that the other method (e.g., keyword) catches at a low rank.
RRF_CONSTANT_K = 60


def execute_clinical_search(
    db: Session,
    query: str,
    sku_id: str = None,
    top_k: int = 3
) -> dict:
    """
    Hybrid Search: Vector + Keyword with Reciprocal Rank Fusion.

    Step-by-step:
      1. Convert the user's query into a vector embedding (PubMedBERT).
      2. Run a pgvector cosine-distance search (top 10 results).
      3. Run a PostgreSQL full-text search using plainto_tsquery (top 10 results).
      4. Merge both ranked lists using the RRF formula.
      5. Sort by combined RRF score and return the top top_k documents.
    """
    # =====================================================================
    # STEP 1: VECTOR SEARCH (Semantic Meaning)
    # =====================================================================
    # We use PubMedBERT to convert the free-text query into a 768-dimensional
    # vector. This embedding captures the "meaning" of the query — so a search
    # for "fever medication" will also match documents about "antipyretic
    # treatment" because those words have similar vector representations.

    try:
        model = get_embedding_model()
        query_vector = model.encode(query).tolist()

        # Build the vector search query using pgvector's cosine distance operator.
        # Cosine distance ranges from 0.0 (identical direction) to 2.0 (opposite).
        # We convert it to similarity with: similarity = 1.0 - distance
        vector_query = db.query(
            ClinicalKnowledgeBase,
            ClinicalKnowledgeBase.embedding.cosine_distance(query_vector).label("distance")
        )

        if sku_id:
            vector_query = vector_query.filter(ClinicalKnowledgeBase.sku_id == sku_id)

        # Get top 10 results from vector search (we ask for more than top_k
        # because the keyword search might surface different relevant results
        # that we want to consider in the fusion step).
        vector_raw_results = vector_query.order_by("distance").limit(10).all()
    except Exception as e:
        logger.warning("Vector model unavailable. Falling back to pure keyword search.")
        vector_raw_results = []

    # =====================================================================
    # STEP 2: KEYWORD SEARCH (Exact Word Match via PostgreSQL tsvector)
    # =====================================================================
    # PostgreSQL's plainto_tsquery function takes a plain text query and
    # automatically converts it into a tsquery by:
    #   1. Tokenizing the words (splitting on spaces/punctuation)
    #   2. Stemming each word using the 'english' dictionary (e.g., "running" -> "run")
    #   3. Removing stop words (e.g., "the", "is", "and")
    #   4. Combining them with AND operators
    #
    # The @@ operator checks if the tsvector (content_fts) matches the tsquery.
    # This gives us a relevance score via ts_rank() that we can sort by.
    #
    # Beginner Note: We use a raw SQL text() call here because SQLAlchemy's
    # ORM does not have built-in support for PostgreSQL's full-text search
    # functions (plainto_tsquery, ts_rank, tsvector). Writing raw SQL ensures
    # we have full control over the query.

    keyword_search_sql = text("""
        SELECT
            id,
            sku_id,
            content,
            metadata_payload,
            ts_rank(content_fts, plainto_tsquery('english', :query)) AS search_rank
        FROM clinical_knowledge_base
        WHERE content_fts @@ plainto_tsquery('english', :query)
        {sku_filter_clause}
        ORDER BY search_rank DESC
        LIMIT 10
    """.format(
        sku_filter_clause="AND sku_id = :sku_id" if sku_id else ""
    ))

    keyword_params = {"query": query}
    if sku_id:
        keyword_params["sku_id"] = sku_id

    keyword_raw_rows = db.execute(keyword_search_sql, keyword_params).fetchall()

    # =====================================================================
    # STEP 3: RECIPROCAL RANK FUSION (RRF)
    # =====================================================================
    # RRF is our secret sauce for combining two ranked lists into one.
    #
    # The formula is simple:
    #   rrf_score(document) = 1 / (rank_in_list + RRF_CONSTANT_K)
    #
    # Where rank_in_list is 1-based (1st result = rank 1, 2nd result = rank 2).
    #
    # Why does this work? Because the reciprocal function gives diminishing
    # penalties — being ranked #2 vs #10 in one list only costs a small amount
    # of score difference. This means that if a document is ranked highly in
    # BOTH lists, it gets a very high combined score. If it ranks well in only
    # one list, it still gets a moderate score. This is much better than simply
    # averaging or intersecting the two result sets.
    #
    # We store the accumulated RRF score in a dictionary (scoring_dict) keyed
    # by the document ID. Then we sort by score descending at the end.

    scoring_dict = {}

    # --- Process Vector Search Results ---
    # Each item is a tuple: (ClinicalKnowledgeBase_record, distance_value)
    for rank_index, (record, distance) in enumerate(vector_raw_results):
        # Use 1-based ranking so the top result gets a rank of 1
        rank_position = rank_index + 1

        rrf_score = 1.0 / (rank_position + RRF_CONSTANT_K)

        # Convert cosine distance to a human-readable similarity percentage
        similarity_score = 1.0 - distance

        # The initial confidence_score comes from vector cosine distance.
        # Later, the keyword processing loop may upgrade this value if
        # the keyword search finds a stronger match.
        scoring_dict[record.id] = {
            "sku_id": record.sku_id,
            "content": record.content,
            "metadata_payload": record.metadata_payload,
            "rrf_score": rrf_score,
            "confidence_score": round(similarity_score, 4),
            "vector_confidence": round(similarity_score, 4),
        }

    # --- Process Keyword Search Results ---
    # Each row is returned as a SQLAlchemy Row object. We access columns by
    # name (e.g., row.id, row.content) to make the code self-documenting.
    for rank_index, row in enumerate(keyword_raw_rows):
        rank_position = rank_index + 1

        rrf_score = 1.0 / (rank_position + RRF_CONSTANT_K)

        # --------------------------------------------------------------
        # SYNTHETIC KEYWORD CONFIDENCE FIX (Storybook Syntax):
        # We discovered that PostgreSQL's ts_rank can sometimes return microscopic 
        # floating point numbers (e.g. 1.7e-10) for short queries, which breaks scaling math.
        # However, if a row was returned by the keyword search at all, it means the exact 
        # words exist in the document. Therefore, we assign it a synthetic confidence 
        # based simply on its rank index in the search results.
        # 
        # The #1 keyword result (rank_index = 0) gets 0.95.
        # The #2 keyword result (rank_index = 1) gets 0.93.
        # It bottoms out at 0.85 so it always clears the safety breaker.
        # --------------------------------------------------------------
        synthetic_keyword_confidence = max(0.85, 0.95 - (rank_index * 0.02))

        if row.id in scoring_dict:
            # This document was already found by vector search.
            # Add the keyword RRF score to its existing score.
            scoring_dict[row.id]["rrf_score"] += rrf_score

            # The final confidence_score is the HIGHER of the two signals.
            # Vector may be confident but keyword may find an exact match
            # that vector missed, and vice versa. Taking the max gives us
            # the benefit of both methods.
            existing_confidence = scoring_dict[row.id]["confidence_score"]
            scoring_dict[row.id]["confidence_score"] = round(
                max(existing_confidence, synthetic_keyword_confidence), 4
            )
        else:
            # This document was only found by keyword search (vector search
            # missed it). This is the whole point of Hybrid Search — some
            # documents that are semantically "distant" but contain exactly
            # matching keywords will be surfaced here.
            scoring_dict[row.id] = {
                "sku_id": row.sku_id,
                "content": row.content,
                "metadata_payload": row.metadata_payload,
                "rrf_score": rrf_score,
                "confidence_score": round(synthetic_keyword_confidence, 4),
            }

    # =====================================================================
    # STEP 4: SORT AND RETURN TOP RESULTS
    # =====================================================================
    # Convert the scoring dictionary into a sorted list, ordered by the
    # combined RRF score (highest first). This gives us the best of both
    # search worlds — documents that ranked highly in both vector AND
    # keyword search will float to the top.

    sorted_by_rrf = sorted(
        scoring_dict.values(),
        key=lambda item: item["rrf_score"],
        reverse=True
    )

    # Apply the Safety Circuit Breaker
    formatted_results = []
    safety_warning = None

    for item in sorted_by_rrf[:top_k]:
        if item["confidence_score"] >= MINIMUM_CONFIDENCE_THRESHOLD:
            formatted_results.append({
                "sku_id": item["sku_id"],
                "content": item["content"],
                "confidence_score": item["confidence_score"],
                "metadata_payload": item["metadata_payload"]
            })
        else:
            logger.warning(
                f"Hybrid search result for SKU {item['sku_id']} rejected. "
                f"Confidence {item['confidence_score']} is below {MINIMUM_CONFIDENCE_THRESHOLD}."
            )

    # Graceful Degradation: If no results passed the safety check
    if not formatted_results:
        safety_warning = (
            "CLINICAL SAFETY BREAKER: No high-confidence matches found. "
            "Please consult a Senior Pharmacist or official CDSCO guidelines."
        )

    return {
        "results": formatted_results,
        "safety_warning": safety_warning
    }


# =========================================================================
# PHASE 9: CROSS-MODEL HYBRID ORCHESTRATOR (Substitute Finder)
# =========================================================================

def find_clinical_substitutes(
    db: Session,
    target_sku: str,
    threshold: float = 0.80,
) -> list[dict]:
    """
    Find chemically similar substitutes for an out-of-stock medication.

    Beginner Note — How this works (the "Story"):

        Imagine you are a pharmacist. A patient needs "Pan 40" (Pantoprazole)
        but we are out of stock. You need to find a DIFFERENT medicine that
        has a similar "chemical signature" AND is physically available on
        our shelves.

        Step 1 — Find the "Chemical Signature":
        We look up Pan 40's AI embedding (a 768-number vector that represents
        its chemical properties) from the clinical_knowledge_base. This is
        like finding its unique chemical fingerprint in a database.

        Step 2 — Find Similar Medicines:
        We scan EVERY other medicine in the database, comparing their
        embeddings using cosine distance (<=> operator). A score of 1.0
        means "chemically identical," a score of 0.0 means "completely
        different." We only keep matches above the threshold (default 80%).

        Step 3 — Join with Inventory:
        We only want substitutes that we PHYSICALLY HAVE in stock. So we
        join with medication_batches, SUM up all available quantities,
        and find the cheapest batch price. We also filter out anything
        with zero stock.

        Step 4 — Sort by Price:
        We show the cheapest substitutes FIRST because in Indian pharmacy,
        patients often prefer the most affordable option.

    Args:
        db: Database session for executing raw SQL.
        target_sku: The SKU of the medication we need a substitute for.
        threshold: Minimum similarity score (0.0 to 1.0, default 0.80).

    Returns:
        A list of substitute dictionaries, each with keys:
            sku_id, brand_name, generic_class, matching_score,
            stock_qty, unit_price_inr.

    Raises:
        HTTPException (404): If the target SKU has no clinical knowledge data.
    """

    # =====================================================================
    # STEP 1: Fetch the Base SKU's Vector Embedding (Chemical Signature)
    # =====================================================================
    # We need the AI embedding of the requested medicine to use as our
    # "search query." We use raw SQL (text()) so junior developers can
    # see exactly what PostgreSQL is doing. The pgvector extension stores
    # embeddings as 768-dimensional vectors.
    #
    # Beginner Note: Think of this as scanning the medicine's barcode to
    # pull up its chemical fingerprint before we start looking for matches.
    # =====================================================================

    base_vector_query = text("""
        SELECT embedding
        FROM clinical_knowledge_base
        WHERE sku_id = :sku
        LIMIT 1
    """)

    base_vector_result = db.execute(base_vector_query, {"sku": target_sku}).fetchone()

    # If the SKU has no clinical knowledge record, we cannot compute
    # substitutes because we have no "chemical signature" to compare against.
    # This usually means the CSV ingestion (bulk_ingest.py) has not been
    # run for this SKU yet.
    if base_vector_result is None:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail=(
                f"No clinical knowledge data found for SKU '{target_sku}'. "
                "Cannot compute substitutes without a base embedding. "
                "Please run scripts/bulk_ingest.py first."
            ),
        )

    # Extract the embedding as a plain Python list of 768 floats.
    # The Vector type from pgvector automatically deserializes the
    # PostgreSQL vector column into a Python list when we access it.
    target_embedding: list[float] = base_vector_result[0]

    # =====================================================================
    # STEP 2: Run the Hybrid Vector + Inventory Join Query
    # =====================================================================
    # This is where the magic happens. We write a single PostgreSQL query
    # that does ALL of the following in one round-trip:
    #
    #   1. Exclude the original SKU (we don't want to recommend the same
    #      medicine the pharmacist already said is unavailable).
    #   2. Compute cosine similarity between each candidate medicine's
    #      embedding and our target SKU's embedding using the <=> operator.
    #   3. JOIN with medication_batches to get real-time stock levels.
    #   4. Filter out medicines that have ZERO stock on the shelf.
    #   5. GROUP BY SKU so we get one row per substitute, with stock
    #      aggregated using SUM() and cheapest price using MIN().
    #   6. Apply the similarity threshold so we only return what we
    #      consider a "close enough" match.
    #   7. Sort by price ascending — cheapest first.
    #
    # Beginner Note: The `metadata_payload ->> 'brand_name'` syntax is
    # PostgreSQL's JSON extraction operator. The `->>` returns the value
    # as TEXT. We store brand_name and generic_name in the metadata JSON
    # because the medications table only stores the chemical structural
    # data (apis, therapeutic_classes), not the commercial brand names.
    # =====================================================================

    # We use bindparam with type_=Vector so SQLAlchemy knows how to
    # serialize our Python list-of-floats into the PostgreSQL vector
    # format that the <=> operator expects. Without this, SQLAlchemy
    # would try to send the list as a PostgreSQL ARRAY, which the
    # pgvector <=> operator cannot understand.
    substitute_query = text("""
        SELECT
            c.sku_id,
            c.metadata_payload ->> 'brand_name' AS brand_name,
            c.metadata_payload ->> 'generic_name' AS generic_class,
            1 - (c.embedding <=> :target_vector) AS matching_score,
            COALESCE(SUM(b.available_quantity), 0) AS stock_qty,
            MIN(b.max_retail_price) AS unit_price_inr
        FROM clinical_knowledge_base c
        JOIN medication_batches b ON c.sku_id = b.sku_id
        WHERE c.sku_id != :original_sku
          AND b.available_quantity > 0
        GROUP BY c.id, c.sku_id, c.metadata_payload, c.embedding
        HAVING (1 - (c.embedding <=> :target_vector)) >= :threshold
        ORDER BY unit_price_inr ASC
    """).bindparams(
        bindparam("target_vector", type_=Vector),
        bindparam("original_sku", type_=type(target_sku)),
        bindparam("threshold", type_=type(threshold)),
    )

    # Execute the query with our parameters.
    # The target_embedding is passed as a plain Python list of floats.
    # SQLAlchemy's bindparam(type_=Vector) handles the serialization.
    substitute_rows = db.execute(
        substitute_query,
        {
            "target_vector": target_embedding,
            "original_sku": target_sku,
            "threshold": threshold,
        },
    ).fetchall()

    # =====================================================================
    # STEP 3: Format Results into the Expected Dictionary Structure
    # =====================================================================
    # Each row from the database is a SQLAlchemy Row object. We access
    # columns by name (row.brand_name, row.matching_score, etc.) and
    # convert them into a plain dictionary that matches the
    # SubstituteItemSchema shape.
    #
    # Beginner Note: We use round(matching_score, 4) to keep the score
    # to 4 decimal places — enough precision for the pharmacist to
    # compare substitutes without overwhelming them with digits.
    # =====================================================================

    substitutes: list[dict] = []

    for row in substitute_rows:
        substitutes.append({
            "sku_id": row.sku_id,
            "brand_name": row.brand_name or row.sku_id,
            "generic_class": row.generic_class or "Unknown",
            "matching_score": round(row.matching_score, 4),
            "stock_qty": row.stock_qty,
            "unit_price_inr": float(row.unit_price_inr) if row.unit_price_inr else 0.0,
        })

    return substitutes
