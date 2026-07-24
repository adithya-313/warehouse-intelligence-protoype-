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

def resolve_drug_entity(db: Session, query: str) -> dict:
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
        
    # We strip hyphens because "PAN-40" should match "PAN 40" or "PAN40"
    query_clean = " ".join(tokens).upper().replace("-", "")
    
    # Check if they typed the exact raw SKU first (like "PAN40")
    # since bare SKUs aren't in the alias table.
    sku_check = text("SELECT sku_id FROM medications WHERE sku_id ILIKE :query LIMIT 1")
    exact_sku = db.execute(sku_check, {"query": query_clean}).fetchone()
    if exact_sku:
        logger.info(f"DrugResolver: Exact bare SKU match found -> {exact_sku[0]}")
        return {"status": "resolved", "sku_id": exact_sku[0], "confidence": "exact"}
        
    # Step 2: Exact alias match
    # Sometimes users type the exact brand name without hyphens (e.g. "PAN 40").
    exact_alias_check = text("""
        SELECT sku_id FROM drug_brand_aliases 
        WHERE REPLACE(alias_text, '-', '') = :query OR REPLACE(alias_text, ' ', '') = :query 
        LIMIT 1
    """)
    exact_alias = db.execute(exact_alias_check, {"query": query_clean.replace(" ", "")}).fetchone()
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
    
    # Fix 2: Boost code-like candidates over plain-word candidates.
    # Code-like tokens (e.g., "PAN40", "AMLOK5", "DOLO650") are structurally much more 
    # likely to be genuine drug references than ordinary English words that coincidentally 
    # share letters with a drug name. We add a fixed boost to any candidate containing a digit.
    CODE_LIKE_CANDIDATE_BOOST = 0.2
    
    # Fix 1: Per-candidate best match, THEN rank globally.
    # The previous SQL applied LIMIT 3 globally across all candidates combined, which allowed 
    # one "loud" word (e.g., "safe" matching 3 unrelated drugs) to fill all 3 slots, pushing 
    # the correct match (e.g., "dolo650") out of the top 3 entirely.
    # The new SQL uses DISTINCT ON to find the SINGLE BEST alias match FOR EACH CANDIDATE WORD 
    # first, applies the code-like boost, and then takes the global top 3 from those winners.
    # Set the word similarity threshold lower so that DOLO650 (0.54) matches DOLO 650 TABLET using <%
    db.execute(text("SET pg_trgm.word_similarity_threshold = 0.5"))
    
    sql = text("""
        WITH per_candidate_best AS (
            SELECT DISTINCT ON (q.candidate) 
                   q.candidate, 
                   a.sku_id, 
                   a.alias_text, 
                   CASE 
                       WHEN q.candidate ~ '[0-9]' THEN word_similarity(q.candidate, a.alias_text) + :boost 
                       ELSE word_similarity(q.candidate, a.alias_text) 
                   END AS score
            FROM unnest(CAST(:candidates AS text[])) AS q(candidate)
            JOIN drug_brand_aliases a ON q.candidate <% a.alias_text
            ORDER BY q.candidate, word_similarity(q.candidate, a.alias_text) DESC
        )
        SELECT candidate, sku_id, alias_text, score 
        FROM per_candidate_best 
        ORDER BY score DESC 
        LIMIT 3;
    """)
    
    results = db.execute(sql, {"candidates": candidates, "boost": CODE_LIKE_CANDIDATE_BOOST}).fetchall()
    
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
        if unique_skus[0]["score"] > 0.5 and (unique_skus[0]["score"] - unique_skus[1]["score"] > 0.15):
            match = unique_skus[0]["sku"]
            logger.info(f"DrugResolver: Confident fuzzy match (best score) -> {match}")
            return {"status": "resolved", "sku_id": match, "confidence": "fuzzy"}
            
        choices = [u["sku"] for u in unique_skus]
        logger.info(f"DrugResolver: Ambiguous fuzzy match, disambiguating -> {choices}")
        return {"status": "disambiguate", "choices": choices[:3]}
