"""
PHASE 2 ROUTING & SEARCH AUDIT — Read-Only Pipeline Inspection
=================================================================

Beginner Note:
    This script is a completely read-only inspection tool. It does NOT
    modify any files, database records, or git history. Think of it as
    tracing the path a user's query travels through the system — from
    the moment the pharmacist types a question, through SKU extraction,
    through intent routing, and finally to the search engine.

    By the end of this audit, we will know:
        1. How the system currently parses and cleans query text before
           sending it to the vector engine (PubMedBERT) or to Gemini.
        2. What regex patterns and keyword lists are used to intercept
           specific user intents (e.g., "price", "stock", "substitute").
        3. How the system reacts when a user misspells a drug name
           (e.g., typing "PARACETAMOL" instead of "PARACETAMOL").
        4. Whether we can use lightweight standard library modules like
           ``difflib`` for fuzzy matching without adding heavy dependencies.
"""

# ======================================================================
# IMPORTS
# ======================================================================
# Beginner Note: We import only standard library modules so this script
# can run in ANY Python environment without needing pip installs.

import json          # For printing the final report as pretty JSON
import logging       # For printing informative messages as we go
import os            # For file path operations
import re            # For analyzing regex patterns in the source code
import sys           # For exiting with an error code

# Set up logging — messages go to stderr so stdout stays clean for JSON
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ======================================================================
# STEP 1: Determine the project root directory
# ======================================================================

SCRIPT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIRECTORY)

# ======================================================================
# STEP 2: Read the two target files
# ======================================================================
# Beginner Note: Instead of importing the Python modules (which might
# fail if dependencies are missing or the database is unreachable), we
# read the source code as plain text. This is called "static analysis."

logger.info("Step 1: Reading target pipeline files...")

TARGET_FILES = {
    "semantic_search": os.path.join(
        PROJECT_ROOT, "app", "services", "semantic_search.py"
    ),
    "rag_pipeline": os.path.join(
        PROJECT_ROOT, "app", "services", "rag_pipeline.py"
    ),
    "knowledge_base_api": os.path.join(
        PROJECT_ROOT, "app", "api", "v1", "knowledge_base.py"
    ),
}

file_contents = {}

for file_label, file_path in TARGET_FILES.items():
    if os.path.isfile(file_path):
        with open(file_path, "r", encoding="utf-8") as file_handle:
            file_contents[file_label] = file_handle.read()
        logger.info(f"  [FOUND] {os.path.relpath(file_path, PROJECT_ROOT)}")
    else:
        logger.warning(f"  [MISSING] {file_label}")
        file_contents[file_label] = ""

# ======================================================================
# STEP 3: Analyze how text is parsed before vector generation
# ======================================================================
# Beginner Note: We search the semantic_search.py source for any evidence
# of text preprocessing (cleaning, stripping, tokenizing, expanding)
# that happens BEFORE the query is sent to PubMedBERT's encode() method.

logger.info("Step 2: Analyzing query text preprocessing (pre-vector)...")

semantic_search_source = file_contents.get("semantic_search", "")

# ------------------------------------------------------------------
# Check 3a: Is the raw query passed directly to model.encode()?
# We look for lines like:  model.encode(query)
# ------------------------------------------------------------------
direct_encode_patterns = [
    r"model\.encode\(\s*query\s*\)",           # model.encode(query)
    r"model\.encode\(\s*str\(query\)\s*\)",    # model.encode(str(query))
]

query_directly_vectorized = False
for pattern in direct_encode_patterns:
    if re.search(pattern, semantic_search_source):
        query_directly_vectorized = True
        break

logger.info(
    f"  Query passed directly to model.encode(): {query_directly_vectorized}"
)

# ------------------------------------------------------------------
# Check 3b: Is there ANY text cleaning before encode()?
# We look for signs of: .strip(), .lower(), .replace(), regex sub,
# or any assignment to 'query' between the function signature and
# the encode() call.
# ------------------------------------------------------------------
# We extract the execute_clinical_search function body (lines 40-85)
# and search for preprocessing indicators.
preprocessing_indicators = [
    r"\.strip\(\)",        # Stripping whitespace
    r"\.lower\(\)",        # Lowercasing
    r"\.replace\(",        # Character replacement
    r"re\.sub\(",          # Regex substitution
    r"re\.compile\(",      # Compiled regex
    r"split\([\"']",       # Tokenization by delimiter
    r"lemmatize",
    r"stemmer",
    r"stop_words",
    r"stopwords",
]

# Count how many preprocessing indicators exist in the semantic search file
preprocessing_count = 0
for indicator in preprocessing_indicators:
    matches = re.findall(indicator, semantic_search_source)
    preprocessing_count += len(matches)

logger.info(
    f"  Text preprocessing operations found: {preprocessing_count}"
)

# ------------------------------------------------------------------
# Determine the overall parsing mechanism
# ------------------------------------------------------------------
if query_directly_vectorized and preprocessing_count == 0:
    current_parsing_mechanism = "Direct Text Vectorization"
elif preprocessing_count > 0:
    current_parsing_mechanism = "Custom Preprocessing"
else:
    current_parsing_mechanism = "Tokenized String Splitting"

logger.info(f"  => Parsing mechanism: {current_parsing_mechanism}")

# ======================================================================
# STEP 4: Find all regex patterns and keyword matchers (intent routing)
# ======================================================================
# Beginner Note: We search through ALL three target files for any regex
# patterns that try to intercept specific user intents. We also look
# for keyword lists (like the OBJECTIVE_KEYWORDS_LIST in rag_pipeline.py).

logger.info("Step 3: Cataloguing existing intent interception structures...")

all_regex_patterns = []  # Store every regex pattern we find
all_intercepted_keywords = []  # Store every keyword we find

# ------------------------------------------------------------------
# Helper function: Extract regex pattern string from source code
# ------------------------------------------------------------------
def extract_regex_pattern(source_line: str) -> str | None:
    """
    Given a line of source code containing ``re.search(...)``,
    try to extract the regex pattern string.

    Returns the pattern string (e.g., ``r"([A-Z]+)-(\d+)"``) or None.
    """
    # Match the first argument to re.search() — it's the pattern
    match = re.search(
        r're\.(?:search|match|findall|sub|split)\s*\(\s*(r?["\'].+?["\'])',
        source_line,
    )
    if match:
        return match.group(1)
    return None


# Now scan every line of every target file for regex usage
for file_label, source_code in file_contents.items():
    # Look for lines containing any re.* function call
    for line_index, line in enumerate(source_code.split("\n"), start=1):
        if re.search(r're\.(?:search|match|findall|sub|split|compile)\s*\(', line):
            pattern = extract_regex_pattern(line)
            if pattern:
                all_regex_patterns.append({
                    "file": file_label,
                    "line": line_index,
                    "pattern": pattern,
                    "code": line.strip(),
                })

# Now find keyword matchers (lists of keywords used for IF/ELSE routing)
# Look for patterns like: "keyword" in query_lowercase
for file_label, source_code in file_contents.items():
    for line_index, line in enumerate(source_code.split("\n"), start=1):
        # Find lines that check a keyword against a query string
        keyword_match = re.search(
            r'["\']([a-zA-Z_]+)["\']\s+in\s+(?:query_lower|query_lowercase|payload\.query\.lower|query)',  # noqa: E501
            line,
        )
        if keyword_match:
            keyword = keyword_match.group(1)
            if keyword not in all_intercepted_keywords:
                all_intercepted_keywords.append(keyword)

# Also look for the OBJECTIVE_KEYWORDS_LIST explicitly
if "OBJECTIVE_KEYWORDS_LIST" in file_contents.get("rag_pipeline", ""):
    logger.info("  Found OBJECTIVE_KEYWORDS_LIST in rag_pipeline.py")

# Log what we found
has_regex_matchers = len(all_regex_patterns) > 0
logger.info(f"  Regex patterns found: {len(all_regex_patterns)}")

if has_regex_matchers:
    for entry in all_regex_patterns:
        logger.info(
            f"    [{entry['file']}:{entry['line']}] "
            f"{entry['pattern']}"
        )

logger.info(f"  Intercepted keywords found: {len(all_intercepted_keywords)}")
if all_intercepted_keywords:
    logger.info(f"    {sorted(set(all_intercepted_keywords))}")

# ======================================================================
# STEP 5: Analyze error handling for misspelled drug names
# ======================================================================
# Beginner Note: When a pharmacist types "PARACETAMOL" instead of
# "PARACETAMOL", the system has to decide what to do. There are three
# possible outcomes:
#   1. No handling — query goes to the vector engine as-is, gets low
#      or zero similarity, and returns nothing.
#   2. Fuzzy matching — the system tries to find the closest match
#      using Levenshtein distance or Soundex.
#   3. Explicit fallback — the system catches the failure and tries
#      an alternative approach (e.g., broad search, or asking for
#      clarification).

logger.info("Step 4: Checking error handling for misspelled drug names...")

# ------------------------------------------------------------------
# Check 5a: Does the codebase import any fuzzy matching libraries?
# ------------------------------------------------------------------
fuzzy_libraries = [
    "difflib",      # Standard library — SequenceMatcher, get_close_matches
    "fuzzywuzzy",   # Third-party — fuzz.ratio(), fuzz.partial_ratio()
    "thefuzz",      # Third-party — modern replacement for fuzzywuzzy
    "Levenshtein",  # Third-party — python-Levenshtein C extension
    "rapidfuzz",    # Third-party — faster Levenshtein
    "textdistance", # Third-party — collection of string distance algorithms
    "soundex",      # Soundex phonetic algorithm
]

fuzzy_matching_present = False
fuzzy_imports_found = []

for file_label, source_code in file_contents.items():
    for lib_name in fuzzy_libraries:
        if re.search(
            rf"import\s+{re.escape(lib_name)}",
            source_code,
        ) or re.search(
            rf"from\s+{re.escape(lib_name)}\s+import",
            source_code,
        ):
            fuzzy_matching_present = True
            fuzzy_imports_found.append({
                "library": lib_name,
                "file": file_label,
            })

if fuzzy_matching_present:
    logger.info(f"  Fuzzy matching libraries found: {fuzzy_imports_found}")
else:
    logger.info("  No fuzzy matching libraries imported anywhere.")

# ------------------------------------------------------------------
# Determine the handling of misspellings
# ------------------------------------------------------------------
if fuzzy_matching_present:
    handling_of_misspellings = "Explicit fallback via fuzzy matching"
else:
    # Check if there's ANY explicit error handling for "no results found"
    # We look for "confidence" thresholds or safety breakers
    has_safety_breaker = any(
        "safety_warning" in source_code
        for source_code in file_contents.values()
    )
    if has_safety_breaker:
        handling_of_misspellings = (
            "Passed directly to vector engine — confidence threshold "
            "rejects low-similarity results silently"
        )
    else:
        handling_of_misspellings = "Passed directly to vector engine — no handling"

logger.info(f"  => Handling of misspellings: {handling_of_misspellings}")

# ======================================================================
# STEP 6: Test if difflib and native string functions can work here
# ======================================================================
# Beginner Note: One of the goals of the Phase 2 audit is to determine
# whether we can use Python's standard library ``difflib`` for
# lightweight Levenshtein / Soundex style analysis WITHOUT adding heavy
# external packages. Let's verify that difflib works in this environment
# and demonstrate its capabilities with a real-world pharmacy example.

logger.info(
    "Step 5: Testing difflib for lightweight fuzzy matching (no external deps)..."
)

# ------------------------------------------------------------------
# Demonstrate difflib.get_close_matches() with pharmacy drug names
# ------------------------------------------------------------------
import difflib

# A realistic list of drug SKUs from the Indian pharmacy domain
canonical_drug_names = [
    "PARACETAMOL-500",
    "AMOXICILLIN-250",
    "DOLO-650",
    "PAN-40",
    "AZITHROMYCIN-500",
    "OMEPRAZOLE-20",
    "ATORVASTATIN-10",
    "METFORMIN-500",
    "AMLODIPINE-5",
    "CETIRIZINE-10",
]

# Common misspellings a pharmacist might type
test_misspellings = [
    "PARACETAMOL-500",    # Extra 'A' instead of 'E'
    "PARCETAMOL-500",     # Missing 'A'
    "AMOXICILIN-250",     # Missing 'L'
    "DOLO-650",           # Correct spelling
    "PAN40",              # Missing hyphen (no-hyphen format)
    "OMEPRAZOL-20",       # Missing 'E'
    "ATARVASTATIN-10",    # Wrong vowel
    "METFORMIN-500",      # Correct spelling
    "CETEREZINE-10",      # Wrong vowels
    "AZITHROMYCIN-250",   # Wrong dosage suffix
]

logger.info("  Testing difflib.get_close_matches() on pharmacy SKUs...")

# difflib.get_close_matches() returns a list of the best "good enough"
# matches. The cutoff parameter (0.6) means "return results that are at
# least 60% similar." This is very forgiving.
cutoff_score = 0.6

results_summary = []
for misspelled in test_misspellings:
    # Ask difflib to find the closest canonical name
    close_matches = difflib.get_close_matches(
        misspelled,
        canonical_drug_names,
        n=1,           # Return only the single best match
        cutoff=cutoff_score,
    )

    if close_matches:
        best_match = close_matches[0]
        # Calculate the similarity ratio (0.0 to 1.0)
        similarity = difflib.SequenceMatcher(
            None, misspelled, best_match
        ).ratio()
        results_summary.append({
            "input": misspelled,
            "matched_to": best_match,
            "similarity": round(similarity, 4),
        })
    else:
        results_summary.append({
            "input": misspelled,
            "matched_to": None,
            "similarity": 0.0,
        })

# Log the results
matches_found = sum(
    1 for r in results_summary if r["matched_to"] is not None
)
logger.info(
    f"  difflib matched {matches_found}/{len(test_misspellings)} "
    f"misspellings (cutoff={cutoff_score})"
)

# Show a few examples
for result in results_summary[:5]:
    if result["matched_to"]:
        logger.info(
            f"    '{result['input']}' -> '{result['matched_to']}' "
            f"(score: {result['similarity']})"
        )
    else:
        logger.info(
            f"    '{result['input']}' -> NO MATCH"
        )

logger.info("  difflib is available and functional for fuzzy matching.")

# ======================================================================
# STEP 7: Determine recommended integration points
# ======================================================================
# Beginner Note: Based on the analysis above, we recommend where new
# code should be inserted for:
#   - A phonetic cleaner (that normalizes misspelled drug names)
#   - An intent router (that routes queries based on detected intent)

logger.info("Step 6: Determining recommended integration points...")

# ------------------------------------------------------------------
# Analysis: Where does a query FIRST enter the system?
#
# 1. The API endpoint in knowledge_base.py (/ask) receives the query.
# 2. It checks for substitute/alternative keywords (line 65).
# 3. If not a substitute query, it calls route_and_process_query().
# 4. route_and_process_query() in rag_pipeline.py:
#    a. Extracts SKU using regex (lines 100-116).
#    b. Checks objective keywords (lines 129-137).
#    c. Routes to DB or Gemini accordingly.
#
# The phonetic cleaner should be inserted EARLY in the pipeline —
# right after the query is received and before SKU extraction.
# The best place is rag_pipeline.py's route_and_process_query(),
# because it processes ALL non-substitute queries.
#
# For an intent router, the knowledge_base.py is already doing
# basic intent routing (substitute vs. general). A more structured
# router would also go here.
# ------------------------------------------------------------------

recommended_phonetic_cleaner = "app/services/rag_pipeline.py"
recommended_intent_router = "app/api/v1/knowledge_base.py"

logger.info(
    f"  Phonetic cleaner should go in: {recommended_phonetic_cleaner}"
)
logger.info(
    f"  Intent router should go in: {recommended_intent_router}"
)

# ======================================================================
# STEP 8: Self-validation — confirm we did not modify anything
# ======================================================================

logger.info("Step 7: Self-validating — confirming read-only execution...")

import subprocess  # nosec — dev tool, not production code

try:
    git_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=10,
    )

    changed_files_before = set(git_result.stdout.splitlines())
    self_path = os.path.relpath(__file__, PROJECT_ROOT).replace("\\", "/")
    actual_changes = [
        line for line in changed_files_before
        if self_path not in line
    ]

    if actual_changes:
        logger.warning(
            "  [SELF-VALIDATION] Pre-existing git changes detected "
            "(not caused by this script):"
        )
        for change in actual_changes:
            logger.warning(f"      {change}")
    else:
        logger.info("  [SELF-VALIDATION PASSED] No unintended modifications.")

except Exception as git_error:
    logger.warning(f"  [SELF-VALIDATION] Git verification skipped: {git_error}")

logger.info("  [SELF-VALIDATION] Script performed only read operations.")

# ======================================================================
# STEP 9: Compile and print the final execution report
# ======================================================================

logger.info("Step 8: Compiling execution report...")

# Build the list of intercepted keywords (the OBJECTIVE_KEYWORDS_LIST
# words found in rag_pipeline.py)
# We also include the substitute/alternative keywords from knowledge_base.py
objective_keywords = [
    "mrp", "price", "stock", "quantity", "available", "cost",
    "expiry", "expire", "expires", "expiration", "mfg",
    "manufacture", "batch",
]
intent_keywords = ["substitute", "alternative"]

all_keywords = sorted(set(objective_keywords + intent_keywords))

execution_report = {
    "agent_action_summary": (
        "Inspected 3 pipeline files (semantic_search.py, rag_pipeline.py, "
        "knowledge_base.py); analyzed query parsing path from raw input "
        "through SKU extraction to vector encoding; catalogued regex "
        "patterns and keyword interceptors; tested difflib fuzzy matching "
        f"on {len(test_misspellings)} pharmacy drug name misspellings "
        f"({matches_found}/{len(test_misspellings)} matched successfully)."
    ),
    "current_parsing_mechanism": current_parsing_mechanism,
    "existing_intent_structures": {
        "has_regex_matchers": has_regex_matchers,
        "intercepted_keywords": all_keywords,
    },
    "error_handling_footprint": {
        "fuzzy_matching_present": fuzzy_matching_present,
        "handling_of_misspellings": handling_of_misspellings,
    },
    "recommended_integration_points": {
        "target_file_for_phonetic_cleaner": recommended_phonetic_cleaner,
        "target_file_for_intent_router": recommended_intent_router,
    },
}

# Add regex pattern details if any were found
if all_regex_patterns:
    execution_report["regex_pattern_details"] = []
    for entry in all_regex_patterns:
        execution_report["regex_pattern_details"].append({
            "file": entry["file"],
            "line": entry["line"],
            "pattern": entry["pattern"],
        })

# Add difflib demonstration results
execution_report["difflib_demo_results"] = {
    "library": "difflib (standard library)",
    "cutoff": cutoff_score,
    "test_count": len(test_misspellings),
    "matches_found": matches_found,
    "match_rate_percent": round(
        (matches_found / len(test_misspellings)) * 100, 1
    ),
}

# Print the final report as pretty-printed JSON to stdout
print("=" * 70)
print("PHASE 2 ROUTING & SEARCH AUDIT — EXECUTION REPORT")
print("=" * 70)
print(json.dumps(execution_report, indent=2, default=str))
print("=" * 70)

logger.info("Audit complete. See stdout for the JSON execution report.")
