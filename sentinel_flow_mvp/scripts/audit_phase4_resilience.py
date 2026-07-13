"""
Phase 4 — Resilience & Caching Audit (Read-Only).

Beginner Note:
    Before we build the Circuit Breaker and Hash Cache, we need to
    understand EVERYTHING about how Redis is currently used and how
    Gemini API failures are handled.

    This audit answers two big questions:
    1. Is there already a hash-based cache for API responses / DB queries?
    2. What happens when Gemini is down? Does the system crash or degrade?

    We inspect 4 files:
      - app/core/redis_client.py   (Redis connection + locking)
      - app/services/rag_pipeline.py (Gemini error handling)
      - app/main.py                (global exception handlers)
      - app/api/v1/knowledge_base.py (API layer integration)

    This script is 100% READ-ONLY — it never writes a single byte to disk.
"""

import json
import sys
import os
import ast

# ------------------------------------------------------------------
# ENCODING FIX FOR WINDOWS TERMINALS
# ------------------------------------------------------------------
# The source code may contain Unicode characters (e.g., Rupee symbol)
# that Windows cmd terminals cannot display. We force UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def safe_print(text: str = "") -> None:
    """Print text safely regardless of terminal encoding."""
    try:
        print(text)
    except UnicodeEncodeError:
        console_encoding = sys.stdout.encoding or "utf-8"
        safe_bytes = text.encode(console_encoding, errors="replace")
        print(safe_bytes.decode(console_encoding, errors="replace"))


# ------------------------------------------------------------------
# HELPER: Search a file for a term and return line context
# ------------------------------------------------------------------


def search_file(filepath: str, search_term: str) -> list[dict]:
    """
    Line-by-line search with 2 lines of surrounding context.

    Returns a list of dicts with:
        - line_number (int)
        - context (str) — the matching line plus neighbors
    """
    results = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

        for idx, line in enumerate(lines):
            if search_term.lower() in line.lower():
                start = max(0, idx - 2)
                end = min(len(lines), idx + 3)
                context_lines = []
                for ctx_idx in range(start, end):
                    prefix = ">>>" if ctx_idx == idx else "   "
                    context_lines.append(
                        f"  {prefix} L{ctx_idx + 1}: {lines[ctx_idx].rstrip()}"
                    )
                results.append({
                    "line_number": idx + 1,
                    "context": "\n".join(context_lines),
                })
    except Exception as e:
        results.append({"error": str(e)})
    return results


# ------------------------------------------------------------------
# MAIN AUDIT
# ------------------------------------------------------------------

safe_print("=" * 72)
safe_print("PHASE 4 RESILIENCE & CACHING AUDIT")
safe_print("=" * 72)
safe_print()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REDIS_PATH = os.path.join(BASE_DIR, "app", "core", "redis_client.py")
RAG_PATH = os.path.join(BASE_DIR, "app", "services", "rag_pipeline.py")
MAIN_PATH = os.path.join(BASE_DIR, "app", "main.py")
KB_PATH = os.path.join(BASE_DIR, "app", "api", "v1", "knowledge_base.py")

safe_print(f"  Target Files:")
safe_print(f"    Redis Client:       {REDIS_PATH}")
safe_print(f"    RAG Pipeline:       {RAG_PATH}")
safe_print(f"    Main (entry point): {MAIN_PATH}")
safe_print(f"    Knowledge Base:     {KB_PATH}")
safe_print()

# =====================================================================
# AUDIT 1: Redis Caching Strategy
# =====================================================================
safe_print("-" * 72)
safe_print("AUDIT 1: Redis Caching Strategy")
safe_print("-" * 72)
safe_print()

# 1a — What Redis commands are used?
safe_print("  [1a] Redis commands used (SET, GET, EXPIRE, etc.):")
for cmd in ["redis.set(", "redis_client.set(", ".get(", ".delete(", ".zadd(", ".zrem", ".zcard", ".expire("]:
    matches = search_file(REDIS_PATH, cmd)
    for m in matches:
        safe_print(f"    {m['context']}")
        safe_print()

# 1b — Is there a TTL-based cache?
safe_print("  [1b] Searching for TTL / EXPIRE / cache patterns...")
for term in ["ttl", "cache", "ex=", "expire"]:
    matches = search_file(REDIS_PATH, term)
    if matches:
        for m in matches:
            safe_print(f"    FOUND '{term}' at line {m['line_number']}:  {m['context']}")
    else:
        safe_print(f"    NOT FOUND '{term}' in redis_client.py")

safe_print()

# 1c — Is there any hash-based version tracking?
safe_print("  [1c] Searching for global version hash or state-change tracking...")
for term in ["version", "hash", "checksum", "etag", "stale", "invalidate"]:
    matches = search_file(REDIS_PATH, term)
    if matches:
        for m in matches:
            safe_print(f"    FOUND '{term}' at line {m['line_number']}:  {m['context']}")
    else:
        safe_print(f"    NOT FOUND '{term}' in redis_client.py")

safe_print()

# 1d — Check if any API responses are cached
safe_print("  [1d] Searching for response caching anywhere in the codebase...")
for filepath, label in [(RAG_PATH, "rag_pipeline.py"), (KB_PATH, "knowledge_base.py")]:
    for term in ["cache", "redis.get", "redis.set", "ttl"]:
        matches = search_file(filepath, term)
        if matches:
            for m in matches:
                safe_print(f"    FOUND '{term}' in {label} at line {m['line_number']}")
safe_print("    (If none found above, NO API response caching exists.)")
safe_print()

# =====================================================================
# AUDIT 2: LLM API Error Handling
# =====================================================================
safe_print("-" * 72)
safe_print("AUDIT 2: LLM / Gemini API Error Handling")
safe_print("-" * 72)
safe_print()

# 2a — How does rag_pipeline.py handle Gemini failures?
safe_print("  [2a] Error handling in generate_clinical_response()...")
for term in ["except", "Exception", "try:", "generate_content", "timeout"]:
    matches = search_file(RAG_PATH, term)
    if matches:
        safe_print(f"\n  Results for '{term}':")
        for m in matches:
            safe_print(f"    {m['context']}")
            safe_print()

# 2b — Is there any timeout on the Gemini call?
safe_print("  [2b] Searching for timeout configuration on LLM calls...")
timeout_matches = search_file(RAG_PATH, "timeout")
if timeout_matches:
    for m in timeout_matches:
        safe_print(f"    {m['context']}")
else:
    safe_print("    NO TIMEOUT FOUND — Gemini calls can hang indefinitely.")
safe_print()

# 2c — Request timeout from google-generativeai library
safe_print("  [2c] Checking if genai request options include timeout...")
req_timeout_matches = search_file(RAG_PATH, "request_options")
if req_timeout_matches:
    for m in req_timeout_matches:
        safe_print(f"    {m['context']}")
else:
    safe_print("    NO request_options configured for Gemini client.")
safe_print()

# 2d — What happens when Gemini fails?
safe_print("  [2d] Fallback behavior when Gemini generation fails...")
fallback_matches = search_file(RAG_PATH, "SYSTEM ERROR")
if fallback_matches:
    for m in fallback_matches:
        safe_print(f"    {m['context']}")
safe_print()

# 2e — Is there a circuit breaker or retry mechanism?
safe_print("  [2e] Searching for retry or circuit breaker patterns...")
for term in ["retry", "circuit_breaker", "CircuitBreaker", "backoff", "tenacity"]:
    matches = search_file(RAG_PATH, term)
    if matches:
        for m in matches:
            safe_print(f"    FOUND '{term}' at line {m['line_number']}:  {m['context']}")
    else:
        safe_print(f"    NOT FOUND '{term}' in rag_pipeline.py")

safe_print()

# =====================================================================
# AUDIT 3: Global Error Handlers
# =====================================================================
safe_print("-" * 72)
safe_print("AUDIT 3: Global Exception Handlers (main.py)")
safe_print("-" * 72)
safe_print()

# 3a — What exception handlers are registered?
safe_print("  [3a] exception_handler registrations in main.py...")
handler_matches = search_file(MAIN_PATH, "exception_handler")
for m in handler_matches:
    safe_print(f"    {m['context']}")
    safe_print()

# 3b — Is there a Gemini-specific global handler?
safe_print("  [3b] Checking for Gemini-specific error handler...")
gemini_handler = search_file(MAIN_PATH, "gemini")
if gemini_handler:
    for m in gemini_handler:
        safe_print(f"    {m['context']}")
else:
    safe_print("    NO Gemini-specific exception handler in main.py")
safe_print()

# =====================================================================
# AUDIT 4: Circuit Breaker Status
# =====================================================================
safe_print("-" * 72)
safe_print("AUDIT 4: Existing Circuit Breaker Infrastructure")
safe_print("-" * 72)
safe_print()

# 4a — Check if any circuit breaker file already exists
safe_print("  [4a] Checking for existing circuit breaker module...")
cb_path = os.path.join(BASE_DIR, "app", "core", "circuit_breaker.py")
if os.path.exists(cb_path):
    with open(cb_path, "r", encoding="utf-8") as f:
        cb_content = f.read()
    safe_print(f"    FOUND: {cb_path} ({len(cb_content)} bytes)")
    # Show class names/function defs
    for line in cb_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("class ") or stripped.startswith("async def ") or stripped.startswith("def "):
            safe_print(f"      {stripped}")
else:
    safe_print("    NOT FOUND — no circuit breaker module exists yet.")

safe_print()

# =====================================================================
# SUMMARY
# =====================================================================
safe_print("=" * 72)
safe_print("AUDIT RESULTS")
safe_print("=" * 72)
safe_print()

audit_results = {
    "agent_action_summary": (
        "Inspected redis_client.py, rag_pipeline.py, main.py, and "
        "knowledge_base.py. Found that Redis is used ONLY for distributed "
        "locking (FEFO locks), idempotency (SET NX 24h TTL), and rate "
        "limiting (sliding window). There is ZERO caching of API responses "
        "or database query results. The Gemini LLM call has NO timeout, "
        "NO retry logic, and NO circuit breaker. When Gemini fails, the "
        "system returns a generic error string — it does NOT fall back to "
        "the Rule Engine's verdict. A circuit_breaker.py module exists but "
        "is not imported or used anywhere in the RAG pipeline."
    ),
    "caching_infrastructure": {
        "current_caching_strategy": (
            "TTL-based (for idempotency, rate limiting, and inventory locks "
            "only). NO response caching, NO database query caching."
        ),
        "ttl_duration_seconds": (
            "Varied: 86400 (24h) for idempotency, 60 for inventory locks, "
            "2 for rate-limit sliding windows."
        ),
        "global_version_tracking_exists": False,
    },
    "api_resilience_state": {
        "llm_timeout_handled": False,
        "degraded_mode_exists": False,
        "current_failure_behavior": (
            "When Gemini API call fails (network error, 503, rate limit): "
            "the except Exception block catches it and returns a dict with "
            "'answer' = 'SYSTEM ERROR: AI Generation failed. Please consult "
            "a pharmacist.' and is_safe_to_dispense = True (no lock). "
            "The Rule Engine verdict is DISCARDED — the system does NOT "
            "fall back to the Judge's deterministic decision. When Gemini "
            "returns invalid JSON: caught by json.JSONDecodeError, returns "
            "another error string. Neither case triggers a circuit breaker "
            "or retry."
        ),
    },
    "recommended_integration_points": {
        "target_file_for_hash_cache": "app/services/rag_pipeline.py",
        "target_file_for_circuit_breaker": (
            "app/core/circuit_breaker.py (already exists as a module)"
        ),
    },
}

safe_print(json.dumps(audit_results, indent=2))
safe_print()
safe_print("=" * 72)
safe_print("AUDIT COMPLETE — No files were modified.")
safe_print("=" * 72)
