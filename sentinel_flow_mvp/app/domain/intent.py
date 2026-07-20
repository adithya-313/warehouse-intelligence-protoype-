"""
Intent bucket enum for the Traffic Cop gate.

Beginner Note:
    Before this file existed, intent was passed around as a plain dict of booleans
    ({"pregnancy": False, "pediatric": False, ...}). That worked but was fragile —
    a typo like "pregnacy" would silently create a new key instead of raising an error.

    This enum replaces the stringly-typed routing decision with a proper type.
    Every function that accepts an IntentBucket knows exactly which four values
    are valid, and the type-checker catches misspellings at compile time.
"""

from enum import Enum


class IntentBucket(str, Enum):
    """
    The four buckets a query can land in after passing through the Traffic Cop.

    Why these four?

        NO_INTENT   — We could not find a drug name AND could not find any
                      inventory keyword. There is nothing useful to do with
                      this query — we return a "please rephrase" message
                      without hitting any database, vector index, or LLM.

        INVENTORY   — We found a drug name (SKU) AND the query contains an
                      objective keyword ("price", "stock", etc.). Route
                      directly to the database — zero AI cost, zero latency.

        CLINICAL    — The query contains pregnancy/pediatric/substitute keywords
                      OR was classified as ambiguous and resolved to the clinical
                      path downstream. Requires vector search + optional LLM.

        AMBIGUOUS   — We found a drug name but NO objective keyword and NO
                      clinical keyword. We do not know what the user wants.
                      The fail-safe is to route to the clinical/RAG path
                      (treating unknown intents as clinical questions is safer
                      than assuming they want raw inventory data).
    """

    NO_INTENT = "no_intent"
    INVENTORY = "inventory"
    CLINICAL = "clinical"
    AMBIGUOUS = "ambiguous"
