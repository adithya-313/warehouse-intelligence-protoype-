"""
Pure-function intent classifier — the "Traffic Cop" gate.

Beginner Note:
    This function is the FIRST decision point in the query funnel. It runs
    BEFORE any database call, vector search, or LLM. Its job is simple:
    look at the query text and decide which of four buckets it belongs in.

    Because it makes zero I/O calls (no DB, no Redis, no network), it is
    trivially testable and trivially fast (~microseconds per call).
"""

from app.domain.intent import IntentBucket
from app.domain.intent_keywords import OBJECTIVE_KEYWORDS


# ---------------------------------------------------------------------------
# KNOWN LIMITATION — please read before you file a bug about misclassification
# ---------------------------------------------------------------------------
# Drug detection in this gate is limited to what the cheap regex-based SKU
# extractor can find: hyphenated codes ("TELMA-40"), bare codes ("TELMA40"),
# and space-separated brand+strength ("calpol 650"). The SQL-backed exact-match
# scan (extract_known_entities) and fuzzy matching (difflib) both run LATER
# in the funnel and are NOT available here because this gate must be pure
# (no I/O).
#
# This means a query like "is crocin safe in pregnancy" will be classified
# as NO_INTENT by this gate — "crocin" is a brand name, not a regex-matching
# SKU, and "safe pregnancy" does not match the objective keyword list.
# This is acceptable because:
#   1. The query still reaches the full RAG pipeline (no data lost).
#   2. extract_known_entities() will later find "CROCIN" via SQL exact match.
#   3. Fuzzy matching (Phase 2, not yet built) will later handle misspellings.
#
# If this limitation causes real-world problems, the fix is to either:
#   a) Add more patterns to the SKU regex (in sanitizer.py).
#   b) Make this gate async with a lightweight in-memory cache of known
#      drug names (Phase 2+ enhancement).
# ---------------------------------------------------------------------------


def classify_intent(
    query: str,
    sku_id: str | None,
    has_objective_keyword: bool,
) -> IntentBucket:
    """
    Classify a query into one of four intent buckets using only the query
    text and a precomputed drug/SKU flag.

    Why does this exist?
        Every query that hits the backend costs money and latency if it goes
        through the full RAG/LLM pipeline. This gate lets us short-circuit
        useless queries (NO_INTENT) and cheap queries (INVENTORY) early.

    Parameters:
        query: The raw user query string (used for length logging only).
        sku_id: A drug SKU if one was already extracted by the regex-based
                extractor, or None if no drug pattern was found.
        has_objective_keyword: True if the query text contains any word from
                               the canonical OBJECTIVE_KEYWORDS list.

    Returns:
        An IntentBucket enum value:
            NO_INTENT  — No drug found → nothing to act on.
            INVENTORY  — Drug found + objective keyword → route to DB.
            AMBIGUOUS  — Drug found but no objective keyword → fail-safe
                         clinical path.
    """
    # ------------------------------------------------------------------
    # Rule 1: No drug was found in the query at all.
    # ------------------------------------------------------------------
    # If there is no drug to look up, an objective keyword alone
    # ("price", "stock") cannot tell us what the user wants —
    # "price" of what? There is nothing to query. Treat as NO_INTENT
    # regardless of whether objective keywords are present.
    if sku_id is None:
        return IntentBucket.NO_INTENT

    # ------------------------------------------------------------------
    # Rule 2: Drug was found AND the query contains an objective keyword.
    # ------------------------------------------------------------------
    # We know exactly what to do: query the database for this drug's
    # price, stock, expiry, etc. Route to INVENTORY.
    if has_objective_keyword:
        return IntentBucket.INVENTORY

    # ------------------------------------------------------------------
    # Rule 3: Drug was found but no objective keyword.
    # ------------------------------------------------------------------
    # We have a drug but do not know what the user wants to do with it.
    # The safest default is AMBIGUOUS — the caller will route to the
    # clinical/RAG path, which may find pregnancy/pediatric/substitute
    # keywords later in the funnel and act on them appropriately.
    return IntentBucket.AMBIGUOUS
