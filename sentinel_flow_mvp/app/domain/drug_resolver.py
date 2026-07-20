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

logger = logging.getLogger(__name__)

def resolve_drug_entity(db: Session, query: str) -> dict:
    """
    Resolve a drug name from the user's query against the catalog.

    Parameters:
        db: Active database session.
        query: The user's cleaned query string.

    Returns:
        dict: A dictionary containing the resolution status.
            - {"status": "resolved", "sku_id": <match>, "confidence": "exact" | "fuzzy"}
            - {"status": "disambiguate", "choices": [<match1>, <match2>, ...]}
            - {"status": "no_match", "reason": "no_close_match_found"}
    """
    # Step 1: Fetch the complete catalog of known drug identifiers.
    # We reuse the exact same helper from rag_pipeline to ensure we are
    # looking at the exact same catalog without duplicating DB logic.
    known_skus, known_brands = get_known_drug_catalog(db)
    
    if not known_skus and not known_brands:
        logger.warning("DrugResolver: Catalog is empty.")
        return {"status": "no_match", "reason": "empty_catalog"}

    query_upper = query.upper()
    
    # Step 2: Attempt EXACT substring match.
    # We prefer longer exact matches just like extract_known_entities.
    matched_entities = []
    for sku in known_skus:
        if sku in query_upper:
            matched_entities.append(sku)
    for brand in known_brands:
        if brand in query_upper:
            matched_entities.append(brand)
            
    if matched_entities:
        # Sort by length descending, pick the longest specific identifier.
        best_exact_match = sorted(set(matched_entities), key=len, reverse=True)[0]
        logger.info(f"DrugResolver: Exact match found -> {best_exact_match}")
        return {"status": "resolved", "sku_id": best_exact_match, "confidence": "exact"}

    # Step 3: If no exact match, attempt FUZZY match.
    # We break the query into tokens and check against the catalog.
    tokens = query.split()
    all_candidates = list(known_skus | known_brands)
    
    fuzzy_matches = set()
    for token in tokens:
        # We don't bother fuzzy matching tiny words
        if len(token) <= 4:
            continue
            
        token_upper = token.upper()
        # difflib.get_close_matches finds close string similarities.
        # Beginner Note: The cutoff here is 0.85, which is intentionally tighter
        # than sanitizer.py's 0.6. Why? Because this function's job is
        # confident disambiguation. If we use 0.6 here, we might confidently
        # guess the wrong drug and dispense wrong clinical advice. 0.85 ensures
        # we only match or disambiguate when the spelling is extremely close.
        # We request up to 3 matches for the disambiguation UI.
        close_matches = difflib.get_close_matches(
            token_upper,
            all_candidates,
            n=3,
            cutoff=0.85
        )
        for match in close_matches:
            fuzzy_matches.add(match)

    if not fuzzy_matches:
        logger.info("DrugResolver: No close match found.")
        return {"status": "no_match", "reason": "no_close_match_found"}
        
    sorted_choices = list(fuzzy_matches)
    # difflib already sorts by score per token, but since we gathered a set
    # we sort again by max similarity against any query token just to be safe.
    sorted_choices.sort(
        key=lambda choice: max(
            difflib.SequenceMatcher(None, choice, t.upper()).ratio() 
            for t in tokens if len(t) > 4
        ),
        reverse=True
    )
    # Cap choices at 3
    sorted_choices = sorted_choices[:3]

    if len(sorted_choices) == 1:
        # Step 4: Exactly one close match found -> confident fuzzy resolve
        match = sorted_choices[0]
        logger.info(f"DrugResolver: Confident fuzzy match found -> {match}")
        return {"status": "resolved", "sku_id": match, "confidence": "fuzzy"}
    else:
        # Step 5: Two or more close matches -> ask the user to pick (disambiguate)
        logger.info(f"DrugResolver: Ambiguous fuzzy match, disambiguating -> {sorted_choices}")
        return {"status": "disambiguate", "choices": sorted_choices}
