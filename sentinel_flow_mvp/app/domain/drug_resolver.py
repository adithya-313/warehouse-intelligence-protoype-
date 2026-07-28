"""
Drug Resolver — Disambiguation and Fuzzy Matching.

Beginner Note:
    This module exists to ensure that a misspelled or ambiguous drug name
    is NEVER silently dropped or guessed incorrectly.
    If the user types "PARCETAMOL" (misspelled), we should either:
      a) Confidently resolve it to "PARACETAMOL" if it's uniquely close.
      b) Ask the user "Did you mean?" if there are multiple close matches.
      c) Explicitly report "No match found" if it's gibberish.

    Order of Operations:
      Step 1: Try an exact substring match against known catalog.
      Step 2: If no exact match, try fuzzy matching (difflib) against the catalog.
      Step 3: Return a structured response (resolved, disambiguate, or no_match).
"""

import logging
import difflib
from sqlalchemy.orm import Session
from app.services.rag_pipeline import get_known_drug_catalog
from app.infrastructure.models import ClinicalKnowledgeBase

logger = logging.getLogger(__name__)

# Words that are safe to strip from a user query before attempting drug name matching.
# By removing grammatical filler, we prevent the fuzzy matcher from generating useless
# candidate phrases like "can i give" or "of crocin for".
FILLER_WORDS = {
    "is", "am", "are", "was", "were", "do", "does", "did", "have", "has", "had", 
    "a", "an", "the", "teh", "what", "waht", "why", "how", "when", "where", "who", "which",
    "can", "could", "would", "should", "will", "shall", "may", "might", "must",
    "i", "me", "my", "we", "us", "our", "you", "your", "he", "him", "his", "she", 
    "her", "it", "its", "they", "them", "their", "to", "for", "with", "about", 
    "of", "in", "on", "at", "by", "from", "after", "before", "and", "or", "but", 
    "if", "then", "else", "vs", "give", "take", "tell", "show", "know", "happen", 
    "happens", "skip", "mix", "cause", "used", "someone"
}

def translate_to_sku(db: Session, match_str: str, known_skus: set[str]) -> str:
    """
    Translate a brand/generic name to its actual SKU ID via DB lookup.
    
    Beginner Note:
        If we found an exact match against a bare SKU (like "PAN40"), we
        just return it. Otherwise, we query the new drug_brand_aliases
        table to find the SKU that owns this specific brand name.
    """
    if match_str in known_skus:
        return match_str
        
    from sqlalchemy import text
    sql = text("SELECT sku_id FROM drug_brand_aliases WHERE alias_text = :match_str LIMIT 1")
    result = db.execute(sql, {"match_str": match_str.upper()}).fetchone()
    if result:
        return result[0]
        
    return match_str

def resolve_drug_entity(db: Session, query: str, sku_id: str | None = None) -> dict:
    # Why: if the caller already knows the exact drug (e.g. the sanitizer already
    # found it, or the user picked it from a disambiguation menu), we trust that
    # and skip fuzzy matching entirely. No need to guess what we already know.
    if sku_id:
        return {"status": "resolved", "sku_id": sku_id, "confidence": "exact"}

    # [DIAG-H3] Logging the exact input the resolver receives
    logger.info(f"[DIAG-H3] resolve_drug_entity input query: '{query}'")
    """
    Resolve a drug name from the user's query against the catalog.

    Beginner Note:
        Instead of pulling tens of thousands of strings into Python and 
        running difflib (which causes an N+1 scaling issue and OOM crashes), 
        we push the fuzzy matching down into PostgreSQL. The pg_trgm extension 
        uses a GIN index to instantly find the closest matching brand or 
        generic name in milliseconds.

    Parameters:
        db: Active database session.
        query: The user's cleaned query string.

    Returns:
        dict: A dictionary containing the resolution status.
            - {"status": "resolved", "sku_id": <match>, "confidence": "exact" | "fuzzy"}
            - {"status": "disambiguate", "choices": [<match1>, <match2>, ...]}
            - {"status": "no_match", "reason": "no_close_match_found"}
    """
    from sqlalchemy import text
    
    # Step 1: Clean the query string
    raw_tokens = query.split()
    tokens = [t.strip(".,;:'\"!?()") for t in raw_tokens if t.strip(".,;:'\"!?()")]
    
    if not tokens:
        logger.warning("DrugResolver: Empty query after stripping punctuation.")
        return {"status": "no_match", "reason": "empty_query"}
        
    query_clean = " ".join(tokens).upper().replace("-", "")
    
    # Step 1: Exact bare SKU match (per token)
    # Why: We check each individual word (token) in the query to see if it perfectly 
    # matches a known bare SKU (e.g. "GENERIC_REF_PARACETAMOL"). If the query is a 
    # full sentence, the exact SKU might just be one word inside it. We cannot expect 
    # the entire sentence to equal the SKU.
    matched_skus = []
    
    # We use exact equality (=) because we uppercase the token, and SKUs are uppercase.
    sku_check = text("SELECT sku_id FROM medications WHERE sku_id = :token LIMIT 1")
    alias_check = text("SELECT sku_id FROM drug_brand_aliases WHERE alias_text ILIKE :token LIMIT 1")
    
    for token in tokens:
        # Strip hyphens just in case they typed "PAN-40" but the DB stores "PAN40"
        token_clean = token.upper().replace("-", "")
        
        row = db.execute(sku_check, {"token": token_clean}).fetchone()
        
        if not row:
            # Fallback: try matching token as exact generic/brand name via aliases
            row = db.execute(alias_check, {"token": token}).fetchone()
            if row:
                logger.info(f"DrugResolver: Token '{token}' matched exact name alias.")
                
        if row:
            found_sku = row[0]
            # Avoid counting the exact same SKU twice if they typed it twice
            if found_sku not in matched_skus:
                matched_skus.append(found_sku)
                
    # [DIAG-H3] Log the exact bare SKUs found
    logger.info(f"[DIAG-H3] exact bare SKU tokens found for query '{query_clean}': {matched_skus}")
    
    if len(matched_skus) == 1:
        logger.info(f"DrugResolver: Exact bare SKU match found -> {matched_skus[0]}")
        return {"status": "resolved", "sku_id": matched_skus[0], "confidence": "exact"}
    elif len(matched_skus) > 1:
        # Why: If the query mentions two different real SKUs (e.g. two drug names), 
        # we do NOT blindly pick one. We log the occurrence and fall through to the 
        # ambiguous/fuzzy path so the system can handle it safely.
        logger.warning(f"DrugResolver: Multiple exact SKU tokens found {matched_skus}, falling through.")
        
    # Step 2: Exact alias match
    # Sometimes users type the exact brand name without hyphens (e.g. "PAN 40").
    exact_alias_check = text("""
        SELECT sku_id FROM drug_brand_aliases 
        WHERE REPLACE(alias_text, '-', '') = :query OR REPLACE(alias_text, ' ', '') = :query 
        LIMIT 1
    """)
    exact_alias = db.execute(exact_alias_check, {"query": query_clean.replace(" ", "")}).fetchone()
    # [DIAG-H3] Log whether it detects an exact alias in the input
    logger.info(f"[DIAG-H3] exact alias check for query '{query_clean.replace(' ', '')}': {exact_alias}")
    if exact_alias:
        logger.info(f"DrugResolver: Exact alias match found -> {exact_alias[0]}")
        return {"status": "resolved", "sku_id": exact_alias[0], "confidence": "exact"}

    # Step 3: Use pg_trgm to find the best fuzzy matches
    # We want to match realistic drug-name candidates against the trigram index.
    # We strip out known filler words, then generate 1, 2, and 3-word sliding windows
    # from the remaining tokens. We batch these candidates into a single UNNEST query.
    
    # Remove filler words
    meaningful_tokens = [t for t in tokens if t.lower() not in FILLER_WORDS]
    
    if not meaningful_tokens:
        logger.info("DrugResolver: Only filler words remained after stripping.")
        return {"status": "no_match", "reason": "no_meaningful_tokens"}
        
    # Generate 1-word, 2-word, and 3-word contiguous windows
    candidates = []
    n = len(meaningful_tokens)
    for window_size in range(1, min(n + 1, 4)):
        for i in range(n - window_size + 1):
            window = " ".join(meaningful_tokens[i:i + window_size]).upper()
            candidates.append(window)
            
    # De-duplicate candidates (e.g. if the user repeated a word)
    candidates = list(set(candidates))
    
    # Beginner Note:
    # We use a GiST index instead of GIN here because GiST natively supports 
    # fast K-Nearest-Neighbor (KNN) sorting. If we used GIN, the database would 
    # have to load thousands of matches into memory and sort them manually!
    # By using GiST and the special distance operator (<<->), PostgreSQL can walk 
    # the index tree and return the closest matches instantly without sorting. 
    # We use word_similarity filter (<%) and distance (<<->) because they allow 
    # matching "dolo650" inside "DOLO 650 TABLET".
    db.execute(text("SET pg_trgm.word_similarity_threshold = 0.5;"))
    sql = text("""
        SELECT q.candidate, a.sku_id, a.alias_text, similarity(q.candidate, a.alias_text) AS score
        FROM unnest(CAST(:candidates AS text[])) AS q(candidate)
        CROSS JOIN LATERAL (
            SELECT sku_id, alias_text
            FROM drug_brand_aliases
            WHERE q.candidate <% alias_text
            ORDER BY q.candidate <<-> alias_text
            LIMIT 50
        ) a
        ORDER BY score DESC
        LIMIT 3;
    """)
    
    results = db.execute(sql, {"candidates": candidates}).fetchall()
    
    if not results:
        logger.info("DrugResolver: No close match found via pg_trgm.")
        return {"status": "no_match", "reason": "no_close_match_found"}
        
    # Step 4: We have matches. Group by SKU to avoid returning the same SKU multiple times.
    unique_skus = []
    seen = set()
    
    for row in results:
        # row structure from UNNEST: (candidate, sku_id, alias_text, score)
        sku = row[1]
        score = row[3]
        # [DIAG-H3] Log every candidate considered with its score before thresholds
        logger.info(f"[DIAG-H3] pg_trgm candidate: sku={sku}, score={score:.4f}, alias_text={row[2]}")
        if sku not in seen:
            seen.add(sku)
            unique_skus.append({"sku": sku, "score": score})
            
    # If there is only one match, or the top match is significantly better than the second
    if len(unique_skus) == 1:
        match = unique_skus[0]["sku"]
        logger.info(f"DrugResolver: Confident fuzzy match found -> {match}")
        return {"status": "resolved", "sku_id": match, "confidence": "fuzzy"}
    else:
        # If the top match is very strong and clearly beats the runner-up
        # [DIAG-H3] Log the exact threshold logic used to decide confident single match vs ambiguous
        top_score = unique_skus[0]['score']
        runner_up = unique_skus[1]['score']
        diff = top_score - runner_up
        logger.info(f"[DIAG-H3] Threshold check: top_score={top_score:.4f} (>0.5?), runner_up={runner_up:.4f}, diff={diff:.4f} (>0.15?)")
        if top_score > 0.5 and diff > 0.15:
            match = unique_skus[0]["sku"]
            logger.info(f"DrugResolver: Confident fuzzy match (best score) -> {match}")
            return {"status": "resolved", "sku_id": match, "confidence": "fuzzy"}
            
        # Check for clean 2-way tie between one generic and one brand
        # Why: If the fuzzy search returns exactly two tied candidates, and exactly one 
        # is a generic reference while the other is a brand, we default to the generic. 
        # This prevents forcing the user to arbitrarily pick a brand for clinical questions.
        if len(unique_skus) == 2:
            sku1 = unique_skus[0]["sku"]
            sku2 = unique_skus[1]["sku"]
            
            is_generic1 = sku1.startswith("GENERIC_REF_")
            is_generic2 = sku2.startswith("GENERIC_REF_")
            
            if is_generic1 and not is_generic2:
                logger.info(f"DrugResolver: Clean 2-way tie between {sku1} and {sku2}, defaulting to generic -> {sku1}")
                return {"status": "resolved", "sku_id": sku1, "confidence": "tie_break_generic_default"}
            elif is_generic2 and not is_generic1:
                logger.info(f"DrugResolver: Clean 2-way tie between {sku1} and {sku2}, defaulting to generic -> {sku2}")
                return {"status": "resolved", "sku_id": sku2, "confidence": "tie_break_generic_default"}
                
        choices = [u["sku"] for u in unique_skus]
        # [DIAG-H3] Log final decision and ambiguous list
        logger.info(f"[DIAG-H3] Final decision: AMBIGUOUS. Candidates: {choices[:3]}")
        logger.info(f"DrugResolver: Ambiguous fuzzy match, disambiguating -> {choices}")
        return {"status": "disambiguate", "choices": choices[:3]}
