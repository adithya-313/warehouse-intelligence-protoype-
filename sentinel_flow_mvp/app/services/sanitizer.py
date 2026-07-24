"""
Query Sanitizer — Structured Multi-Intent Query Preprocessor.
===============================================================

Beginner Note:
    Before the Phase 2 sanitizer, user queries were passed directly to the
    vector engine or to Gemini with zero preprocessing. A misspelled drug
    name like "PARCETAMOL" instead of "PARACETAMOL" would silently fail
    to match anything — the vector engine would return low confidence
    results and the safety breaker would reject them.

    The QuerySanitizer fixes this by intercepting the query BEFORE it
    reaches any search or AI pipeline. It does three things:

    1. FUZZY DRUG NAME CLEANING:
       It uses Python's built-in ``difflib`` module (standard library —
       no external dependencies!) to compare each word in the query
       against a list of valid drug names. If a close match is found
       (60% similarity or higher), the misspelled word is replaced with
       the correct name.

    2. INTENT DETECTION:
       It scans the query for keywords that tell us WHAT the user wants:
         - Are they asking about pregnancy safety?
         - Are they asking about a child's dosage?
         - Do they want a substitute for an out-of-stock drug?
         - Is it a simple objective question (price, stock, etc.)?

    3. SKU EXTRACTION:
       It uses a single unified regex pattern to find drug SKU codes
       (like "AMOXI-500" or "PAN40") anywhere in the query text.
"""

# ======================================================================
# IMPORTS
# ======================================================================
# Beginner Note: We use ONLY the Python standard library here. No
# third-party packages, no SQLAlchemy, no database connections.
# This means the sanitizer can be imported and tested in ANY
# environment, even without a running database container.

import difflib       # Standard library — provides get_close_matches for fuzzy matching
import logging       # Standard library — for logging what the sanitizer does
import re            # Standard library — for regex-based SKU extraction

# Canonical source of truth for what counts as an "objective" keyword.
# Every file that needs to check for objective keywords imports from here.
from app.domain.intent_keywords import OBJECTIVE_KEYWORDS

# Set up a logger so we can see what the sanitizer is doing
logger = logging.getLogger(__name__)


# ======================================================================
# THE QUERYSANITIZER CLASS
# ======================================================================

class QuerySanitizer:
    """
    A preprocessor that cleans, analyses, and enriches user queries before
    they are sent to the search engine or AI pipeline.

    Think of this class as a "quality control inspector" at a factory:
    it checks every incoming query for misspellings, identifies what the
    user is trying to do, and extracts any medication SKU codes.

    Usage:
        sanitizer = QuerySanitizer()

        # Step 1: Fix any misspelled drug names
        cleaned_query = sanitizer.clean_drug_names(
            "what is the price of Crooosin",
            valid_names=["CROCIN", "DOLO-650", "PAN-40"]
        )
        # cleaned_query = "what is the price of CROCIN"

        # Step 2: Figure out what the user wants
        intents = sanitizer.extract_intents(cleaned_query)
        # intents = {"pregnancy": False, "pediatric": False,
        #            "substitute": False, "objective": True}

        # Step 3: Extract any SKU codes from the query
        sku = sanitizer.extract_sku(cleaned_query)
        # sku = None (no SKU in this example)
    """

    # ==================================================================
    # CONSTANTS: Keyword lists for intent detection
    # ==================================================================
    # Beginner Note: These lists define the keywords that map to each
    # intent category. We store them as class-level constants so they
    # are easy to find and modify without digging through methods.

    # Keywords that indicate the user is asking about pregnancy safety.
    PREGNANCY_KEYWORDS = [
        "pregnant",
        "pregnancy",
        "expecting",
        "maternity",
    ]

    # Keywords that indicate the user is asking about children or infants.
    PEDIATRIC_KEYWORDS = [
        "child",
        "kid",
        "toddler",
        "infant",
        "baby",
        "pediatric",
    ]

    # Keywords that indicate the user wants a substitute for a drug.
    SUBSTITUTE_KEYWORDS = [
        "substitute",
        "alternative",
        "replace",
    ]

    # OBJECTIVE_KEYWORDS is now imported from app/domain/intent_keywords.py
    # (the canonical single source of truth). See top of this file.

    # ==================================================================
    # METHOD 1: clean_drug_names(query, valid_names) -> str
    # ==================================================================

    def clean_drug_names(
        self,
        query: str,
        valid_names: list[str],
    ) -> str:
        """
        Tokenize the query into individual words, then check each word
        that is LONGER than 4 characters against the list of valid drug
        names. If ``difflib.get_close_matches`` finds a close match
        (60% similarity or higher), replace the misspelled word with the
        correct one.

        Beginner Note:
            Why do we only check words longer than 4 characters? Short
            words like "the", "is", "of", "for" are common English words
            that would accidentally match unrelated drug names. For
            example, the word "for" is only 3 characters — it should
            never be fuzzy-matched to a drug name. The 4-character
            threshold is a safe guard that prevents false positives.

        Args:
            query: The user's raw query string (e.g., "price of Crooosin").
            valid_names: A list of correctly-spelled drug names or SKUs
                (e.g., ["CROCIN", "DOLO-650", "PAN-40"]).

        Returns:
            The cleaned query string with misspelled words replaced.
            If no misspellings were found, the original query is returned
            unchanged.
        """
        # Step 1: Split the query into individual words (tokens).
        # We split on any whitespace (spaces, tabs). This gives us a
        # list like: ["what", "is", "the", "price", "of", "Crooosin"]
        tokens = query.split()

        # Step 2: Create a flag to track whether we made any corrections.
        # This is useful for logging — we only log a message if something
        # actually changed.
        any_corrections_made = False

        # Step 3: Normalize all names to UPPERCASE for comparison.
        # Beginner Note: Python's difflib is CASE-SENSITIVE. If we pass
        # "Crooosin" (lowercase 'c') and "CROCIN" (uppercase), difflib
        # will think they are completely different strings (ratio 0.14).
        # However, "CROOOSIN" vs "CROCIN" has a ratio of 0.71 — well
        # above our 0.6 cutoff. By normalizing both sides to uppercase,
        # we get accurate case-insensitive fuzzy matching.
        valid_names_upper = [name.upper() for name in valid_names]

        # Step 4: Loop through each word in the query and check if it
        # looks like a misspelled drug name.
        for index, token in enumerate(tokens):
            # Only check words longer than 4 characters to avoid
            # accidentally matching short common words.
            if len(token) <= 4:
                continue

            # Convert the token to uppercase before passing to difflib
            token_upper = token.upper()

            # Ask difflib to find the single best match for this word
            # from the list of valid drug names. The cutoff of 0.6 means
            # "the word must be at least 60% similar to be considered
            # a match." This is deliberately forgiving — it catches
            # common misspellings like "PARCETAMOL" -> "PARACETAMOL"
            # (which is ~97% similar) without being so loose that it
            # matches completely unrelated words.
            close_matches = difflib.get_close_matches(
                token_upper,
                valid_names_upper,
                n=1,            # Return only the single best match
                cutoff=0.6,     # 60% similarity threshold
            )

            # If we found a close match, replace the token
            if close_matches:
                best_match = close_matches[0]

                # Only replace if the matched name is actually different
                # from the original token. If they are the same (exact
                # match), there is nothing to correct.
                if best_match != token_upper:
                    tokens[index] = best_match
                    any_corrections_made = True
                    logger.info(
                        f"QuerySanitizer: Corrected misspelling "
                        f"'{token}' -> '{best_match}'"
                    )

        # Step 4: Join the tokens back into a single string.
        cleaned_query = " ".join(tokens)

        if any_corrections_made:
            logger.info(
                f"QuerySanitizer: Final cleaned query: '{cleaned_query}'"
            )
        else:
            logger.info(
                "QuerySanitizer: No misspellings detected. "
                "Query passed through unchanged."
            )

        return cleaned_query

    # ==================================================================
    # METHOD 2: extract_intents(query) -> dict
    # ==================================================================

    def extract_intents(self, query: str) -> dict:
        """
        Analyse the query and return a dictionary of boolean flags
        indicating which intents the user likely has.

        Beginner Note:
            This method does NOT use a large language model or any AI.
            It simply checks whether specific keywords appear anywhere
            in the query text. This is fast (microseconds), deterministic
            (same input always produces the same output), and requires
            zero external services.

        Args:
            query: The user's query string (already cleaned of
                misspellings, but the original query also works).

        Returns:
            A dictionary with four boolean keys:
                - "pregnancy": True if the query mentions pregnancy.
                - "pediatric": True if the query mentions children.
                - "substitute": True if the user wants a replacement.
                - "objective": True if the query is a simple fact query.
        """
        # Step 1: Convert the query to lowercase for case-insensitive
        # matching. This ensures that "PREGNANT", "Pregnant", and
        # "pregnant" all match the same keyword.
        query_lower = query.lower()

        # Step 2: Check each intent category by looking for any of its
        # keywords in the lowercase query. We use a helper approach:
        # for each category, we loop through its keywords and if ANY
        # keyword appears in the query, we set the flag to True.
        #
        # We use simple for-loops instead of list comprehensions so
        # that a junior developer can clearly see the logic.

        # --- Check for pregnancy intent ---
        pregnancy_detected = False
        for keyword in self.PREGNANCY_KEYWORDS:
            if keyword in query_lower:
                pregnancy_detected = True
                logger.info(
                    f"QuerySanitizer: Detected pregnancy intent "
                    f"(keyword: '{keyword}')"
                )
                break  # No need to check the remaining keywords

        # --- Check for pediatric intent ---
        pediatric_detected = False
        for keyword in self.PEDIATRIC_KEYWORDS:
            if keyword in query_lower:
                pediatric_detected = True
                logger.info(
                    f"QuerySanitizer: Detected pediatric intent "
                    f"(keyword: '{keyword}')"
                )
                break

        # --- Check for substitute intent ---
        substitute_detected = False
        for keyword in self.SUBSTITUTE_KEYWORDS:
            if keyword in query_lower:
                substitute_detected = True
                logger.info(
                    f"QuerySanitizer: Detected substitute intent "
                    f"(keyword: '{keyword}')"
                )
                break

        # --- Check for objective intent ---
        # We use the module-level OBJECTIVE_KEYWORDS imported from
        # app/domain/intent_keywords.py (the canonical source).
        objective_detected = False
        for keyword in OBJECTIVE_KEYWORDS:
            if keyword in query_lower:
                objective_detected = True
                logger.info(
                    f"QuerySanitizer: Detected objective intent "
                    f"(keyword: '{keyword}')"
                )
                break

        # Step 3: Return all four flags as a dictionary.
        return {
            "pregnancy": pregnancy_detected,
            "pediatric": pediatric_detected,
            "substitute": substitute_detected,
            "objective": objective_detected,
        }

    # ==================================================================
    # METHOD 3: extract_sku(query) -> str | None
    # ==================================================================

    def extract_sku(self, query: str) -> str | None:
        """
        Extract a medication SKU code from the query text using a single
        unified regex pattern.

        Beginner Note:
            In the old code, there were TWO separate regex patterns in
            TWO different files (rag_pipeline.py AND knowledge_base.py)
            that tried to do the same thing. If one pattern failed but
            the other succeeded, the behaviour was inconsistent.

            This method consolidates both patterns into ONE method:
            it first tries the hyphenated format (e.g., "AMOXI-500"),
            and if that does not match, it tries the no-hyphen format
            (e.g., "PAN40" -> "PAN-40") by inserting the hyphen before
            the trailing digits.

        Args:
            query: The user's query string (e.g., "What is the price
                of DOLO-650?" or "I need AMOXI500").

        Returns:
            The extracted SKU string in the canonical format
            (e.g., "DOLO-650" or "AMOXI-500"), or None if no SKU
            pattern was found in the query.
        """
        # Step 1: Try the hyphenated pattern first.
        # This matches patterns like "AMOXI-500", "PAN-40", "DOLO-650"
        # where letters are followed by a hyphen and then digits.
        sku_match = re.search(
            r"([A-Z]+)-(\d+)",
            query,
            re.IGNORECASE,  # Case-insensitive so "dolo-650" also matches
        )

        if sku_match:
            # Extract the letter part and digit part, then combine them
            # in the canonical format with uppercase letters and a hyphen.
            sku_id = f"{sku_match.group(1).upper()}-{sku_match.group(2)}"
            logger.info(
                f"QuerySanitizer: Extracted SKU '{sku_id}' from query "
                f"(hyphenated pattern)."
            )
            return sku_id

        # Step 2: If no hyphen was found, try the no-hyphen pattern.
        # This matches patterns like "PAN40", "AMOXI500", "DOLO650"
        # where letters are immediately followed by digits with no
        # separator. We insert a hyphen before the trailing digits
        # to convert it into the canonical format.
        sku_match = re.search(
            r"([A-Z]+)(\d+)",
            query,
            re.IGNORECASE,
        )

        if sku_match:
            sku_id = f"{sku_match.group(1).upper()}-{sku_match.group(2)}"
            logger.info(
                f"QuerySanitizer: Extracted SKU '{sku_id}' from query "
                f"(no-hyphen pattern — hyphen inserted)."
            )
            return sku_id

        # Step 3: Try the space-separated brand/strength pattern.
        # This matches queries like "calpol 650", "pan 40", "augmentin 625"
        # where the brand name is separated from the strength by a space.
        # We strip the space and produce a bare code (no hyphen) matching
        # the DB storage format.
        sku_match = re.search(
            r"\b([A-Z]{2,})\s+(\d+)\b",
            query,
            re.IGNORECASE,
        )

        if sku_match:
            sku_id = f"{sku_match.group(1).upper()}{sku_match.group(2)}"
            logger.info(
                f"QuerySanitizer: Extracted SKU '{sku_id}' from query "
                f"(space-separated pattern — bare code)."
            )
            return sku_id

        # Step 4: No SKU pattern found anywhere in the query.
        logger.info(
            "QuerySanitizer: No SKU pattern found in query."
        )
        return None
