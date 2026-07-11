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
from sqlalchemy import text
from sqlalchemy.orm import Session
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
            ts_rank(content_fts, plainto_tsquery('english', :query)) AS relevance_score
        FROM clinical_knowledge_base
        WHERE content_fts @@ plainto_tsquery('english', :query)
        {sku_filter_clause}
        ORDER BY relevance_score DESC
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

        scoring_dict[record.id] = {
            "sku_id": record.sku_id,
            "content": record.content,
            "metadata_payload": record.metadata_payload,
            "rrf_score": rrf_score,
            "confidence_score": round(similarity_score, 4),
        }

    # --- Process Keyword Search Results ---
    # Each row is returned as a SQLAlchemy Row object. We access columns by
    # name (e.g., row.id, row.content) to make the code self-documenting.
    for rank_index, row in enumerate(keyword_raw_rows):
        rank_position = rank_index + 1

        rrf_score = 1.0 / (rank_position + RRF_CONSTANT_K)

        if row.id in scoring_dict:
            # This document was already found by vector search.
            # Add the keyword RRF score to its existing score.
            scoring_dict[row.id]["rrf_score"] += rrf_score
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
                "confidence_score": 0.0,  # No vector similarity available
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
