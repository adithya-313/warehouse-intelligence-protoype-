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

def translate_to_sku(db: Session, match_str: str, known_skus: set[str]) -> str:
    """Translate a brand/generic name to its actual SKU ID via DB lookup."""
    if match_str in known_skus:
        return match_str
        
    # TODO (Optimization): This re-queries the full ClinicalKnowledgeBase table. 
    # Since it's called in a loop for multiple choices, it creates an N-query pattern.
    # While N is small (capped at 3), a future optimization should have 
    # get_known_drug_catalog() return a pre-built brand-to-SKU dictionary mapping.
    ckb_rows = db.query(ClinicalKnowledgeBase.sku_id, ClinicalKnowledgeBase.metadata_payload).all()
    for row in ckb_rows:
        payload = row.metadata_payload or {}
        if isinstance(payload, dict):
            brand = payload.get("brand_name", "").upper()
            generic = payload.get("generic_name", "").upper()
            if match_str == brand or match_str == generic:
                return row.sku_id
                
    return match_str

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

    # Fix D: Strip punctuation before tokenizing or matching.
    # Case 4 RCA: Quotes and commas degraded difflib ratio from >0.9 to 0.77.
    # We strip trailing/leading punctuation from tokens and rebuild the query string.
    raw_tokens = query.split()
    tokens = [t.strip(".,;:'\"!?()") for t in raw_tokens if t.strip(".,;:'\"!?()")]
    query_upper = " ".join(tokens).upper()
    
    # Fix B: SKU format mismatch. We normalize both the query and the catalog
    # by stripping hyphens (e.g. "TELMA-40" vs "TELMA40") so they can match,
    # but we append the original 'sku' or 'brand' so we return the real bare ID.
    query_normalized = query_upper.replace("-", "")
    
    # Step 2: Attempt EXACT substring match.
    # We prefer longer exact matches just like extract_known_entities.
    matched_entities = []
    for sku in known_skus:
        if sku.replace("-", "") in query_normalized:
            matched_entities.append(sku)
    for brand in known_brands:
        if brand.replace("-", "") in query_normalized:
            matched_entities.append(brand)
            
    if matched_entities:
        # Sort by length descending, pick the longest specific identifier.
        best_exact_match = sorted(set(matched_entities), key=len, reverse=True)[0]
        real_sku = translate_to_sku(db, best_exact_match, known_skus)
        logger.info(f"DrugResolver: Exact match found -> {best_exact_match} (Resolved to SKU: {real_sku})")
        return {"status": "resolved", "sku_id": real_sku, "confidence": "exact"}

    # Step 3: If no exact match, attempt FUZZY match.
    all_candidates = list(known_skus | known_brands)
    # Map normalized candidates back to their real catalog identifiers
    normalized_to_original = {c.replace("-", ""): c for c in all_candidates}
    all_candidates_normalized = list(normalized_to_original.keys())
    
    fuzzy_matches = set()
    for token in tokens:
        # Fix C: Only skip pure alphabetic tokens that are <= 4 chars (e.g., "the", "for").
        # If it has a digit (e.g. "pn40", "40"), it is likely a SKU and should NOT be skipped.
        # This prevents skipping short-but-valid codes.
        if token.isalpha() and len(token) <= 4:
            continue
            
        token_normalized = token.upper().replace("-", "")
        # difflib.get_close_matches finds close string similarities.
        # Beginner Note: The cutoff here is 0.85, which is intentionally tighter
        # than sanitizer.py's 0.6. Why? Because this function's job is
        # confident disambiguation. If we use 0.6 here, we might confidently
        # guess the wrong drug and dispense wrong clinical advice. 0.85 ensures
        # we only match or disambiguate when the spelling is extremely close.
        # We request up to 3 matches for the disambiguation UI.
        close_matches = difflib.get_close_matches(
            token_normalized,
            all_candidates_normalized,
            n=3,
            cutoff=0.85
        )
        for match in close_matches:
            fuzzy_matches.add(normalized_to_original[match])

    if not fuzzy_matches:
        logger.info("DrugResolver: No close match found.")
        return {"status": "no_match", "reason": "no_close_match_found"}
        
    sorted_choices = list(fuzzy_matches)
    # difflib already sorts by score per token, but since we gathered a set
    # we sort again by max similarity against any query token just to be safe.
    sorted_choices.sort(
        key=lambda choice: max(
            difflib.SequenceMatcher(None, choice.replace("-", ""), t.upper().replace("-", "")).ratio() 
            for t in tokens if not (t.isalpha() and len(t) <= 4)
        ),
        reverse=True
    )
    # Cap choices at 3
    sorted_choices = sorted_choices[:3]

    # Translate choices to real SKUs so downstream logic doesn't fail on brand names
    real_choices = []
    seen = set()
    for choice in sorted_choices:
        real_sku = translate_to_sku(db, choice, known_skus)
        if real_sku not in seen:
            seen.add(real_sku)
            real_choices.append(real_sku)

    if len(real_choices) == 1:
        # Step 4: Exactly one close match found -> confident fuzzy resolve
        match = real_choices[0]
        logger.info(f"DrugResolver: Confident fuzzy match found -> {sorted_choices[0]} (Resolved to SKU: {match})")
        return {"status": "resolved", "sku_id": match, "confidence": "fuzzy"}
    else:
        # Step 5: Two or more close matches -> ask the user to pick (disambiguate)
        logger.info(f"DrugResolver: Ambiguous fuzzy match, disambiguating -> {real_choices}")
        return {"status": "disambiguate", "choices": real_choices}
