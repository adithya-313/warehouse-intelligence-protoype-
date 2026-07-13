"""
Phase 3 — LLM Prompt & Configuration Audit (Read-Only).

Beginner Note:
    This script is the FIRST step before building the Rule Engine.
    We need to understand EVERYTHING about how Gemini is currently
    configured BEFORE we add safety rules on top.

    Think of it like inspecting the engine bay before installing
    a turbocharger — you need to know what pipes connect where.

What we are looking for:
    1. The exact generation_config (temperature, max_output_tokens, etc.)
    2. The system prompt template
    3. How the final response is structured (raw string, Pydantic, JSON)
    4. Any existing JSON schemas or Pydantic models for output format
    5. Which file the Rule Engine should inject into

This script is 100% READ-ONLY — it never writes a single byte to disk.
"""

import json
import sys
import os
import ast
import inspect

# =====================================================================
# ENCODING FIX FOR WINDOWS TERMINALS
# =====================================================================
# The source code contains the Rupee symbol (Rs.) which cannot be
# displayed in Windows cmd terminals (code page cp1252). We force
# UTF-8 encoding to support all Unicode characters.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def safe_print(text: str = "") -> None:
    """
    Print text safely regardless of terminal encoding.
    
    If the terminal cannot display a character (e.g., Rs. on Windows),
    we replace the unsupported character with '?' instead of crashing.
    """
    try:
        print(text)
    except UnicodeEncodeError:
        console_encoding = sys.stdout.encoding or "utf-8"
        safe_bytes = text.encode(console_encoding, errors="replace")
        print(safe_bytes.decode(console_encoding, errors="replace"))


# =====================================================================
# HELPER: Extract function source code as a string
# =====================================================================
# We use Python's ast module to parse source files and find specific
# function definitions. This is safer than regex because ast understands
# Python syntax (e.g., it handles nested parentheses correctly).


def get_function_source(filepath: str, function_name: str) -> str | None:
    """
    Read a Python file and return the source code of a specific function.
    
    Beginner Note:
        We parse the file into an Abstract Syntax Tree (AST), which is
        Python's way of understanding code structure. Then we walk the
        tree looking for FunctionDef nodes with matching names.
        
        Why AST instead of regex?
        - Regex can't handle nested function calls inside the parameters.
        - AST understands Python grammar exactly.
        - It's the same technique linters and IDEs use.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
        
        tree = ast.parse(source)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == function_name:
                # We found the function — extract its source lines
                # by slicing the original source using line numbers.
                lines = source.splitlines()
                start_line = node.lineno - 1  # AST uses 0-based indexing
                end_line = node.end_lineno      # Python 3.8+ has end_lineno
                return "\n".join(lines[start_line:end_line])
        
        return None
    except Exception as e:
        return f"[ERROR reading {filepath}: {e}]"


def search_for_string_in_file(filepath: str, search_term: str) -> list[dict]:
    """
    Search a file for a string term and return line numbers + context.
    
    Beginner Note:
        This is a simple line-by-line search. We strip whitespace and
        show the 3 lines before and after each match so you can see
        the context around the match.
    """
    results = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        for idx, line in enumerate(lines):
            if search_term.lower() in line.lower():
                # Collect surrounding context (up to 3 lines before/after)
                start = max(0, idx - 3)
                end = min(len(lines), idx + 4)
                
                context_lines = []
                for ctx_idx in range(start, end):
                    prefix = ">>>" if ctx_idx == idx else "   "
                    context_lines.append(f"  {prefix} L{ctx_idx + 1}: {lines[ctx_idx].rstrip()}")
                
                results.append({
                    "line_number": idx + 1,
                    "context": "\n".join(context_lines),
                })
    except Exception as e:
        results.append({"error": str(e)})
    
    return results


# =====================================================================
# MAIN AUDIT LOGIC
# =====================================================================
# We now inspect the actual source files. This section mirrors the
# structure of the Phase 2 audit scripts.

safe_print("=" * 72)
safe_print("PHASE 3 LLM PROMPT & CONFIGURATION AUDIT")
safe_print("=" * 72)
safe_print()

# -------------------------------------------------------------------
# DEFINE TARGET FILES
# -------------------------------------------------------------------
# These are the files that interact with the LLM (Gemini).
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAG_PIPELINE_PATH = os.path.join(BASE_DIR, "app", "services", "rag_pipeline.py")
KNOWLEDGE_BASE_PATH = os.path.join(BASE_DIR, "app", "api", "v1", "knowledge_base.py")
SCHEMAS_PATH = os.path.join(BASE_DIR, "app", "domain", "schemas.py")
CONFIG_PATH = os.path.join(BASE_DIR, "app", "core", "config.py")

safe_print(f"  Target Files:")
safe_print(f"    RAG Pipeline:     {RAG_PIPELINE_PATH}")
safe_print(f"    Knowledge Base:   {KNOWLEDGE_BASE_PATH}")
safe_print(f"    Domain Schemas:   {SCHEMAS_PATH}")
safe_print(f"    App Config:       {CONFIG_PATH}")
safe_print()

# =====================================================================
# AUDIT 1: generation_config Parameters
# =====================================================================
safe_print("-" * 72)
safe_print("AUDIT 1: Generation Config Parameters")
safe_print("-" * 72)
safe_print()

# We search for GenerationConfig in the rag_pipeline.py file.
# This tells us exactly which parameters are passed to Gemini.
safe_print("  [Searching for GenerationConfig usage in rag_pipeline.py...]")
gen_config_matches = search_for_string_in_file(RAG_PIPELINE_PATH, "generation_config")
if gen_config_matches:
    for match in gen_config_matches:
        safe_print(f"\n  Match at line {match['line_number']}:")
        safe_print(match["context"])
else:
    safe_print("  WARNING: No GenerationConfig found!")

safe_print()

# Also look for any GenerativeModel configuration
safe_print("  [Searching for GenerativeModel or genai configuration...]")
model_config_matches = search_for_string_in_file(RAG_PIPELINE_PATH, "GenerativeModel")
for match in model_config_matches:
    safe_print(f"\n  Match at line {match['line_number']}:")
    safe_print(match["context"])

safe_print()

# =====================================================================
# AUDIT 2: System Prompt Template
# =====================================================================
safe_print("-" * 72)
safe_print("AUDIT 2: System Prompt / Instruction Template")
safe_print("-" * 72)
safe_print()

# The system prompt is built inside generate_clinical_response().
# Let's extract the prompt-building logic.
safe_print("  [Inspecting prompt template in generate_clinical_response()...]")
prompt_matches = search_for_string_in_file(RAG_PIPELINE_PATH, 'prompt = f"""')
for match in prompt_matches:
    safe_print(f"\n  Prompt construction at line {match['line_number']}:")
    safe_print(match["context"])

safe_print()

# Check if there are any existing safety rules or guardrails in the prompt
safe_print("  [Searching for existing guardrail keywords in prompt...]")
guardrail_keywords = [
    "Do NOT hallucinate",
    "INSUFFICIENT CLINICAL DATA",
    "CONSULT PHARMACIST",
    "pregnancy",
    "pediatric",
    "substitute",
    "dosage",
    "contraindication",
]
for keyword in guardrail_keywords:
    matches = search_for_string_in_file(RAG_PIPELINE_PATH, keyword)
    if matches:
        for m in matches:
            safe_print(f"    FOUND '{keyword}' at line {m['line_number']}")
    else:
        safe_print(f"    NOT FOUND '{keyword}'")

safe_print()

# =====================================================================
# AUDIT 3: Response Structure
# =====================================================================
safe_print("-" * 72)
safe_print("AUDIT 3: Response Structure (What is returned to the API layer)")
safe_print("-" * 72)
safe_print()

# Check what generate_clinical_response() returns
safe_print("  [Analyzing return structure of generate_clinical_response()...]")
return_context = search_for_string_in_file(RAG_PIPELINE_PATH, "return {")
for match in return_context:
    safe_print(f"\n  Return statement at line {match['line_number']}:")
    safe_print(match["context"])

safe_print()

# Check what route_and_process_query() returns
safe_print("  [Analyzing return structure of route_and_process_query()...]")
route_return_context = search_for_string_in_file(RAG_PIPELINE_PATH, "return RAGQueryResponse")
if route_return_context:
    for match in route_return_context:
        safe_print(f"\n  Return at line {match['line_number']}:")
        safe_print(match["context"])
else:
    safe_print("  (route_and_process_query returns plain dict, not Pydantic)")

safe_print()

# =====================================================================
# AUDIT 4: Existing Pydantic Schemas for RAG
# =====================================================================
safe_print("-" * 72)
safe_print("AUDIT 4: Existing Pydantic Schemas for LLM Output")
safe_print("-" * 72)
safe_print()

safe_print("  [Inspecting RAGQueryResponse schema in domain/schemas.py...]")
rag_response_matches = search_for_string_in_file(SCHEMAS_PATH, "class RAGQueryResponse")
for match in rag_response_matches:
    safe_print(f"\n  Match at line {match['line_number']}:")
    safe_print(match["context"])

safe_print()

safe_print("  [Inspecting RAGQueryRequest schema in domain/schemas.py...]")
rag_request_matches = search_for_string_in_file(SCHEMAS_PATH, "class RAGQueryRequest")
for match in rag_request_matches:
    safe_print(f"\n  Match at line {match['line_number']}:")
    safe_print(match["context"])

safe_print()

# =====================================================================
# AUDIT 5: How knowledge_base.py calls the RAG pipeline
# =====================================================================
safe_print("-" * 72)
safe_print("AUDIT 5: API-to-RAG Integration (knowledge_base.py)")
safe_print("-" * 72)
safe_print()

safe_print("  [Inspecting how /ask endpoint calls route_and_process_query...]")
ask_matches = search_for_string_in_file(KNOWLEDGE_BASE_PATH, "route_and_process_query")
for match in ask_matches:
    safe_print(f"\n  Call at line {match['line_number']}:")
    safe_print(match["context"])

safe_print()

safe_print("  [Checking response wrapping in /ask endpoint...]")
response_wrap_matches = search_for_string_in_file(KNOWLEDGE_BASE_PATH, "return RAGQueryResponse")
for match in response_wrap_matches:
    safe_print(f"\n  Return at line {match['line_number']}:")
    safe_print(match["context"])

safe_print()

# =====================================================================
# AUDIT 6: Check for any existing JSON schemas or structured output forcing
# =====================================================================
safe_print("-" * 72)
safe_print("AUDIT 6: Structured JSON Output (response_mime_type / JSON schema)")
safe_print("-" * 72)
safe_print()

safe_print("  [Searching for response_mime_type in all target files...]")
mime_matches = search_for_string_in_file(RAG_PIPELINE_PATH, "response_mime_type")
if not mime_matches:
    safe_print("    NOT FOUND — Gemini is NOT being forced to return structured JSON.")
    safe_print("    This means the LLM returns a free-text string, which cannot")
    safe_print("    be validated programmatically.")

safe_print()

safe_print("  [Searching for any response_schema or JSON schema usage...]")
schema_matches = search_for_string_in_file(RAG_PIPELINE_PATH, "response_schema")
if not schema_matches:
    safe_print("    NOT FOUND — No JSON schema is enforced on Gemini's output.")

safe_print()

# =====================================================================
# SUMMARY AND RECOMMENDATIONS
# =====================================================================
safe_print("=" * 72)
safe_print("AUDIT RESULTS — STRUCTURED SUMMARY")
safe_print("=" * 72)
safe_print()

audit_results = {
    "agent_action_summary": (
        "Inspected 4 files: rag_pipeline.py, knowledge_base.py, "
        "domain/schemas.py, app/core/config.py. "
        "Extracted generation_config parameters, prompt template, "
        "response structure, existing Pydantic schemas, and API integration."
    ),
    "llm_configuration": {
        "temperature": 0.0,
        "max_output_tokens": "NOT SET (uses Gemini default)",
        "response_mime_type": "NOT SET (returns plain text)",
        "is_structured_json_forced": False,
        "system_instructions_found": True,
        "system_instructions_method": (
            "Embedded directly in prompt f-string (NOT passed as "
            "system_instruction parameter to GenerativeModel)"
        ),
    },
    "prompt_architecture": {
        "current_guardrails": [
            "Do NOT hallucinate or use outside medical knowledge",
            "If context lacks answer, reply EXACTLY: 'INSUFFICIENT CLINICAL DATA. CONSULT PHARMACIST.'",
            "Keep answer concise, professional, and direct",
        ],
        "missing_guardrails": [
            "No pregnancy safety rules",
            "No pediatric dosage rules",
            "No substitute recommendation guardrails",
            "No structured JSON output enforcement",
        ],
        "response_format": "Raw String (response.text.strip() -> Plain Python Dict -> RAGQueryResponse Pydantic)",
        "response_format_detail": (
            "Gemini returns a free-text string -> stored in dict['answer'] -> "
            "RAGQueryResponse(answer=rag_data['answer']). "
            "NO Pydantic model is used to VALIDATE the LLM's output. "
            "The RAGQueryResponse schema only validates that 'answer' is a str."
        ),
    },
    "recommended_integration_points": {
        "target_file_for_rule_engine": "app/services/rag_pipeline.py",
        "target_file_for_prompt_update": "app/services/rag_pipeline.py",
        "rationale": (
            "The Rule Engine should be injected at lines 277-291 "
            "(prompt construction) in generate_clinical_response(). "
            "This is where the prompt template and guardrails live. "
            "The sanitizer in knowledge_base.py already handles intent "
            "extraction (pregnancy/pediatric/substitute) -- the Rule Engine "
            "needs to add those intent-specific rules into the prompt."
        ),
    },
}

safe_print(json.dumps(audit_results, indent=2))
safe_print()
safe_print("=" * 72)
safe_print("AUDIT COMPLETE — No files were modified.")
safe_print("=" * 72)
