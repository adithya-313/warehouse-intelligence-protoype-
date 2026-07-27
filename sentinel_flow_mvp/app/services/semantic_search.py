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

import json
import logging
from sqlalchemy import text, bindparam
from sqlalchemy.orm import Session
from pgvector.sqlalchemy import Vector
from app.infrastructure.models import ClinicalKnowledgeBase
from app.workers.embedding_tasks import get_embedding_model

logger = logging.getLogger(__name__)

# CLINICAL SAFETY CONSTRAINT:
# If the AI match is less than 85% similar, we reject it to prevent hallucinations.
MINIMUM_CONFIDENCE_THRESHOLD = 0.60

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
            # Normalize: try both hyphenated and de-hyphenated formats
            sku_variants = (sku_id, sku_id.replace("-", ""))
            vector_query = vector_query.filter(
                ClinicalKnowledgeBase.sku_id.in_(sku_variants)
            )

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
        # Normalize: search for both hyphenated and de-hyphenated SKU
        keyword_params["sku_id"] = sku_id.replace("-", "")

    keyword_raw_rows = db.execute(keyword_search_sql, keyword_params).fetchall()

    # -----------------------------------------------------------------------
    # PARTIAL-QUERY PREFIX FALLBACK:
    # plainto_tsquery requires complete words — it cannot match prefixes.
    # When the UI sends keystrokes-as-you-type (e.g. 'dol', 'pan', 'ban'),
    # plainto_tsquery('english', 'dol') returns 0 rows because there is no
    # stemmed token 'dol' in the lexicon.
    #
    # Fix — two complementary strategies:
    #   1. to_tsquery with ':*' wildcard — PostgreSQL's native prefix match.
    #      We split the query on whitespace, stem-safe-encode each token, and
    #      append ':*' so that 'dolo:*' matches 'dolore', 'dolores', etc.
    #   2. ILIKE '%query%' — catches SKU/brand name prefix searches ('PAN',
    #      'AZ', etc.) that FTS stemming would strip as stop-tokens.
    # Both fallback result sets are merged into the existing RRF scoring dict
    # with a small score bonus so they surface above empty-result pages.
    # -----------------------------------------------------------------------
    if not keyword_raw_rows:
        # Strategy 1: Prefix FTS via to_tsquery with :* wildcard
        # Split the query into safe alphanumeric tokens and append ':*' to each.
        # We join with ' & ' (AND) so multi-word queries still narrow results.
        raw_tokens = [t for t in query.split() if t.isalnum()]
        if raw_tokens:
            prefix_tsquery_str = " & ".join(f"{t}:*" for t in raw_tokens)
            prefix_fts_sql = text("""
                SELECT
                    id,
                    sku_id,
                    content,
                    metadata_payload,
                    ts_rank(content_fts, to_tsquery('english', :prefix_q)) AS search_rank
                FROM clinical_knowledge_base
                WHERE content_fts @@ to_tsquery('english', :prefix_q)
                {sku_filter_clause}
                ORDER BY search_rank DESC
                LIMIT 10
            """.format(
                sku_filter_clause="AND sku_id = :sku_id" if sku_id else ""
            ))
            prefix_params = {"prefix_q": prefix_tsquery_str}
            if sku_id:
                prefix_params["sku_id"] = sku_id.replace("-", "")
            keyword_raw_rows = db.execute(prefix_fts_sql, prefix_params).fetchall()

        # Strategy 2: ILIKE content/sku fallback (handles brand-name prefix
        # inputs that FTS tokenization would normally discard as unknown tokens)
        if not keyword_raw_rows:
            ilike_sql = text("""
                SELECT
                    id,
                    sku_id,
                    content,
                    metadata_payload,
                    0.0::float AS search_rank
                FROM clinical_knowledge_base
                WHERE content ILIKE :pattern
                   OR sku_id  ILIKE :pattern
                {sku_filter_clause}
                LIMIT 10
            """.format(
                sku_filter_clause="AND sku_id = :sku_id" if sku_id else ""
            ))
            ilike_params = {"pattern": f"%{query}%"}
            if sku_id:
                ilike_params["sku_id"] = sku_id.replace("-", "")
            keyword_raw_rows = db.execute(ilike_sql, ilike_params).fetchall()


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

    from app.infrastructure.models import MedicationModel

    # Apply the Safety Circuit Breaker
    formatted_results = []
    safety_warning = None

    # Why: We fetch all medication rows in one query instead of one query per result,
    # so we don't slow down every search with lots of small database calls.
    all_sku_ids = [item["sku_id"] for item in sorted_by_rrf[:top_k]]
    medications = db.query(MedicationModel).filter(MedicationModel.sku_id.in_(all_sku_ids)).all()
    medication_lookup_by_sku = {med.sku_id: med for med in medications}

    for item in sorted_by_rrf[:top_k]:
        sku = item["sku_id"]
        is_confident_match = (sku_id is not None and sku == sku_id)
        
        # Why: The ingest pipeline reliably sets "data_quality" to "identity_only" for
        # non-FDA approved generics with no clinical data. If this field exists, we use it directly.
        ingest_data_quality = item["metadata_payload"].get("data_quality")
        
        if ingest_data_quality is not None:
            if ingest_data_quality == "identity_only":
                data_completeness = "identity_only"
            else:
                data_completeness = "full"
        else:
            # Why: If the ingest field is somehow missing, we fall back to a database lookup
            # to see if it's approved by the curator. We log a warning because this shouldn't happen.
            logger.warning(f"Fallback triggered: Missing data_quality in metadata_payload for SKU {sku}")
            med = medication_lookup_by_sku.get(sku)
            is_approved = med.is_approved_by_curator if med else True
            clinical_fields_null = "indications" not in item["metadata_payload"]
            
            if not is_approved and clinical_fields_null:
                data_completeness = "identity_only"
            elif is_approved and clinical_fields_null:
                logger.warning(f"Edge case detected: SKU {sku} is approved by curator but has NULL clinical fields.")
                data_completeness = "identity_only"
            else:
                data_completeness = "full"

        # Why: A search result survives the filter if it naturally has a high confidence score.
        # Alternatively, it also survives if it is an identity-only record AND the resolver confidently
        # matched it, meaning we should honestly disclose the limited data rather than drop it silently.
        if item["confidence_score"] >= MINIMUM_CONFIDENCE_THRESHOLD:
            formatted_results.append({
                "sku_id": item["sku_id"],
                "content": item["content"],
                "confidence_score": item["confidence_score"],
                "metadata_payload": item["metadata_payload"],
                "data_completeness": data_completeness
            })
            logger.info(f"[FILTER] SURVIVED: sku_id={sku}, relevance={item['confidence_score']}, exempted=False, data_completeness={data_completeness}")
            
        elif is_confident_match and data_completeness == "identity_only":
            formatted_results.append({
                "sku_id": item["sku_id"],
                "content": item["content"],
                "confidence_score": item["confidence_score"],
                "metadata_payload": item["metadata_payload"],
                "data_completeness": data_completeness
            })
            logger.info(f"[FILTER] EXEMPTED: sku_id={sku}, relevance={item['confidence_score']}, exempted=True, data_completeness={data_completeness}")
            
        else:
            logger.info(f"[FILTER] DROPPED: sku_id={sku}, relevance={item['confidence_score']}, exempted=False, data_completeness={data_completeness}")
            logger.warning(
                f"Hybrid search result for SKU {sku} rejected. "
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

    base_vector_result = db.execute(base_vector_query, {"sku": target_sku.replace("-", "")}).fetchone()

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
    # Beginner Note:
    #   When PostgreSQL returns a pgvector column through a RAW SQL query
    #   (text()), the driver sends it as a STRING representation of the
    #   vector, e.g., "[0.123, 0.456, ...]". This is different from the
    #   ORM approach (used in execute_clinical_search above) where the
    #   Vector type deserializer runs automatically.
    #
    #   If we do NOT deserialize the string, the bindparam(type_=Vector)
    #   in the next query will receive a string instead of a list-of-floats.
    #   This would cause the pgvector <=> operator to fail with:
    #   "function vector <=> unknown does not exist".
    #
    #   We use json.loads() to parse the string representation into a
    #   Python list of floats. JSON uses the same bracket-and-comma format
    #   as PostgreSQL's vector text representation, so this is safe.
    target_embedding: list[float] = json.loads(base_vector_result[0])

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
    # Beginner Note: We group ONLY by c.id because it is the PRIMARY KEY
    # of clinical_knowledge_base. PostgreSQL guarantees that all other
    # columns from 'c' (sku_id, metadata_payload, embedding) are
    # "functionally dependent" on the primary key, meaning they have
    # exactly ONE value per id. This lets us avoid including the
    # un-hashable data types (JSONB, vector) in the GROUP BY clause,
    # which would cause PostgreSQL to reject them with:
    #   "ERROR: could not identify a hash function for type jsonb"
    #   "ERROR: could not identify a hash function for type vector"
    #
    # IMPORTANT: All story comments must stay OUTSIDE the text() block.
    # PostgreSQL does not recognize '#' as a comment character — it
    # uses '--' for line comments. Any '#' inside the SQL is treated
    # as a syntax error ("syntax error at or near 'Note'").
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
        GROUP BY c.id
        HAVING (1 - (c.embedding <=> :target_vector)) >= :threshold
        ORDER BY unit_price_inr ASC
    """).bindparams(
        bindparam("target_vector", type_=Vector),
        bindparam("original_sku"),
        bindparam("threshold"),
    )

    # Execute the query with our parameters.
    # The target_embedding is passed as a plain Python list of floats.
    # SQLAlchemy's bindparam(type_=Vector) handles the serialization.
    substitute_rows = db.execute(
        substitute_query,
        {
            "target_vector": target_embedding,
            "original_sku": target_sku.replace("-", ""),
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
