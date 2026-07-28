"""
Canonical objective-keyword list for the Intent Gate.

Beginner Note:
    Before this file existed, the list of "what counts as an inventory keyword"
    was duplicated in TWO files (sanitizer.py and rag_pipeline.py) with slightly
    different members in each. That meant a query containing "left" (as in "how
    many left?") would be classified as objective by one file but not the other.

    This module is the SINGLE SOURCE OF TRUTH. Every other file imports from here.
    If you need to add a new keyword (e.g. "count", "units"), add it here and
    every component that cares about intents will automatically pick it up.
"""

# Every word the user might type that signals an inventory-style fact question:
# price checks, stock counts, expiry dates, batch numbers, manufacturing details.
# We keep this as a simple list of lowercase words, all checked case-insensitively.
OBJECTIVE_KEYWORDS: list[str] = [
    "mrp",
    "price",
    "stock",
    "left",
    "quantity",
    "available",
    "cost",
    "expiry",
    "expire",
    "expires",
    "expiration",
    "mfg",
    "manufacture",
    "batch",
]

# Keywords that indicate the user is naming multiple drugs intentionally
# to ask about comparisons or interactions.
COMPARISON_KEYWORDS: list[str] = [
    "vs",
    "versus",
    "difference",
    "and",
    "together",
    "or",
    "compare",
    "compared to",
    "interaction",
    "interact",
    "with",
]
