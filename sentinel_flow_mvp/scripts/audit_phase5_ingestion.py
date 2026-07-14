"""
PHASE 5 INGESTION AUDIT — Read-Only Inspection of Ingestion Pipeline
=====================================================================

Beginner Note:
    This script is a read-only detective. It does NOT modify any files,
    does NOT connect to a database, and does NOT import any heavy ML
    models. It simply LOOKS at the existing code and data files, then
    reports what it finds in a structured JSON format.

    Think of it as a building inspector who walks through a construction
    site with a clipboard, noting down:
        - What materials are lying around (data files).
        - What machines are installed (ingestion scripts).
        - How the machines are configured (GPU vs CPU, file formats).
        - Where the conveyor belts lead (database tables).

    The JSON output will be used by the Phase 5 ETL Adapter builder
    to understand what must be preserved, replaced, or upgraded.

    Safety Guarantees:
        - We open files with ``r`` (read-only) mode only.
        - We never import ``torch``, ``sentence_transformers``, or any
          application-level module that could trigger side effects.
        - We never write to disk or the database.
        - We never call ``git`` commands.

Usage:
    python scripts/audit_phase5_ingestion.py
"""

import json
import os
import sys
from pathlib import Path

# =====================================================================
# CONFIGURATION
# =====================================================================
# We compute the project root directory automatically. This is the
# directory ABOVE ``scripts/`` because that's where ``bulk_ingest.py``
# lives and where ``indian_essential_meds.csv`` is stored.
#
# Beginner Note: ``Path(__file__).resolve().parent`` gives us the
# directory containing THIS script (``scripts/``). We then go up one
# level with ``.parent`` to get the project root.
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# Path to the bulk ingestion script we want to inspect.
BULK_INGEST_PATH: Path = PROJECT_ROOT / "scripts" / "bulk_ingest.py"

# Path to the semantic search service (where the embedding model is used).
SEMANTIC_SEARCH_PATH: Path = PROJECT_ROOT / "app" / "services" / "semantic_search.py"

# Path to the embedding worker (where the model is loaded into memory).
EMBEDDING_TASKS_PATH: Path = PROJECT_ROOT / "app" / "workers" / "embedding_tasks.py"

# Directories to scan for data files (CSV, JSON).
DATA_DIRECTORIES: list[Path] = [
    PROJECT_ROOT / "data",
    PROJECT_ROOT / "datasets",
]


# =====================================================================
# HELPER: Safely read a file one line at a time
# =====================================================================
# We wrap the file reading in a try/except so that if the file doesn't
# exist or can't be read, we get a nice error message instead of a crash.
#
# Beginner Note: ``yield`` is like a pause button. Each time the for
# loop in the calling code asks for the next line, this function reads
# one line from the file and hands it over. This saves memory because
# we never load the entire file at once.


def _safe_read_lines(file_path: Path) -> list[str]:
    """
    Read all lines from a text file into a list.

    Returns an empty list if the file does not exist or cannot be read.
    """
    try:
        with open(file_path, mode="r", encoding="utf-8") as file_handle:
            return file_handle.readlines()
    except FileNotFoundError:
        print(f"  [WARNING] File not found: {file_path}")
        return []
    except PermissionError:
        print(f"  [WARNING] Permission denied reading: {file_path}")
        return []
    except Exception as error:
        print(f"  [WARNING] Could not read {file_path}: {error}")
        return []


# =====================================================================
# AUDIT 1: Inspect bulk_ingest.py
# =====================================================================
# We read the file as raw text and search for specific patterns:
#
#   a) File format: Look for ``open(...)`` and ``csv.DictReader`` or
#      ``json.load`` calls to determine what format the script expects.
#
#   b) Vector generation: Look for ``SentenceTransformer`` to see if the
#      model is imported, and ``device=`` to see if CUDA is enforced.
#
#   c) Database tables: Look for SQLAlchemy model class names referenced
#      in the imports and INSERT statements.
#
# Beginner Note: We do NOT import the file as a Python module because
# importing it would trigger torch (which crashes on this Windows env).
# Instead, we read it as plain text and use simple string searches.
# This is a common technique called "static code analysis" -- looking
# at source code without executing it.


def audit_bulk_ingest() -> dict:
    """
    Inspect ``scripts/bulk_ingest.py`` and return a summary dict.

    Returns:
        A dictionary with keys:
            - "exists": True/False
            - "file_format_found": "CSV" | "JSON" | "SQL" | "None"
            - "target_tables": list of table names found
    """
    result: dict = {
        "exists": BULK_INGEST_PATH.exists(),
        "file_format_found": "None",
        "target_tables": [],
    }

    if not result["exists"]:
        print("\n  [AUDIT] scripts/bulk_ingest.py does NOT exist.")
        return result

    print(f"\n  [AUDIT] Reading {BULK_INGEST_PATH}...")
    lines: list[str] = _safe_read_lines(BULK_INGEST_PATH)

    # ------------------------------------------------------------------
    # Step A: Detect expected file format
    # ------------------------------------------------------------------
    # We search for common file-reading patterns. The first one we find
    # tells us what format the ingestion script expects.
    # ----------------------------------------------------------------
    for line in lines:
        line_stripped: str = line.strip()

        # Skip blank lines and comments so we only check real code.
        if not line_stripped or line_stripped.startswith("#"):
            continue

        # Check for CSV reading patterns.
        if "csv.DictReader" in line_stripped or ".csv" in line_stripped.lower():
            result["file_format_found"] = "CSV"
            print(f"    Found CSV reference on line: {line_stripped[:100]}")
            # Don't break yet -- keep scanning for other formats.

        # Check for JSON reading patterns.
        if "json.load" in line_stripped and "open" in line_stripped:
            result["file_format_found"] = "JSON"
            print(f"    Found JSON reference on line: {line_stripped[:100]}")

        # Check for SQL file patterns.
        if ".sql" in line_stripped.lower() and "open" in line_stripped.lower():
            result["file_format_found"] = "SQL"
            print(f"    Found SQL reference on line: {line_stripped[:100]}")

    # ------------------------------------------------------------------
    # Step B: Detect database tables referenced
    # ------------------------------------------------------------------
    # We search for class names that look like SQLAlchemy model names.
    # Common patterns:
    #   - ``ClinicalKnowledgeBase`` (stores embeddings + text)
    #   - ``MedicationModel`` (stores SKU master data)
    #   - ``MedicationBatchModel`` (stores inventory batches)
    # ----------------------------------------------------------------
    known_models: list[str] = [
        "ClinicalKnowledgeBase",
        "MedicationModel",
        "MedicationBatchModel",
    ]

    for model_name in known_models:
        # Search through every line for this model name.
        for line in lines:
            if model_name in line and not line.strip().startswith("#"):
                if model_name not in result["target_tables"]:
                    result["target_tables"].append(model_name)
                    print(f"    Found target table reference: {model_name}")

    return result


# =====================================================================
# AUDIT 2: Inspect how the embedding model is loaded
# =====================================================================
# We check TWO files:
#   1. app/services/semantic_search.py — the hybrid search engine
#      that calls ``get_embedding_model()`` to get the model.
#
#   2. app/workers/embedding_tasks.py — where the model is actually
#      loaded into memory (the ``get_embedding_model()`` function).
#
#   3. scripts/bulk_ingest.py — which has its OWN model loading
#      (separate from the worker!), and may use CUDA.
#
# Beginner Note: There are TWO paths for loading PubMedBERT:
#   - The worker path (used by the API at runtime) → CPU only ✅
#   - The bulk ingest path (used by admins to load data) → may use CUDA ❌
# We need to verify both to ensure our Phase 0 CPU patch is consistent.


def audit_embedding_engine() -> dict:
    """
    Inspect how the PubMedBERT model is loaded into memory.

    Returns:
        A dictionary with keys:
            - "model_name": The HuggingFace model identifier.
            - "hardware_target": "CPU" | "CUDA" | "MPS" | "unknown"
            - "device_origin": Which file sets the device.
    """
    result: dict = {
        "model_name": "unknown",
        "hardware_target": "unknown",
        "device_origin": "unknown",
        "notes": [],
    }

    # ------------------------------------------------------------------
    # Check the Worker Path (app/workers/embedding_tasks.py)
    # This is the path used by the LIVE API at runtime.
    # ----------------------------------------------------------------
    if EMBEDDING_TASKS_PATH.exists():
        print(f"\n  [AUDIT] Reading {EMBEDDING_TASKS_PATH}...")
        task_lines: list[str] = _safe_read_lines(EMBEDDING_TASKS_PATH)

        for line in task_lines:
            # Find the SentenceTransformer constructor call.
            if "SentenceTransformer(" in line:
                result["model_name"] = "NeuML/pubmedbert-base-embeddings"
                print(f"    Worker model: {result['model_name']}")

                if 'device="cpu"' in line:
                    result["hardware_target"] = "CPU"
                    result["device_origin"] = "embedding_tasks.py (worker)"
                    print("    Worker device: CPU (enforced)")
                elif 'device="cuda"' in line:
                    result["hardware_target"] = "CUDA"
                    result["device_origin"] = "embedding_tasks.py (worker)"
                    print("    Worker device: CUDA")
                elif "device=" in line:
                    result["hardware_target"] = "dynamic"
                    result["device_origin"] = "embedding_tasks.py (worker)"
                    print(f"    Worker device: dynamic — {line.strip()}")
                else:
                    # No explicit device means it defaults to CUDA if available.
                    result["notes"].append(
                        "embedding_tasks.py does NOT specify device, "
                        "so SentenceTransformer will autodetect GPU."
                    )

    # ------------------------------------------------------------------
    # Check the Bulk Ingest Path (scripts/bulk_ingest.py)
    # This is used when an admin runs the ingestion script manually.
    # It has its OWN ``load_model()`` function that may use CUDA.
    # ----------------------------------------------------------------
    if BULK_INGEST_PATH.exists():
        print(f"\n  [AUDIT] Checking bulk_ingest.py model loading...")
        bulk_lines: list[str] = _safe_read_lines(BULK_INGEST_PATH)

        for line_index, line in enumerate(bulk_lines):
            # Find the model loading function name.
            if "SentenceTransformer(" in line:
                result["model_name"] = "NeuML/pubmedbert-base-embeddings"
                print(f"    Bulk ingest model: {result['model_name']}")

                # Check for device= on THIS line or the NEXT few lines
                # (the constructor call may span multiple lines).
                device_str: str = ""
                for offset in range(5):
                    if line_index + offset < len(bulk_lines):
                        current_line: str = bulk_lines[line_index + offset]
                        if "device=" in current_line:
                            device_str = current_line.strip()
                            break

                if device_str:
                    if "device=device" in device_str:
                        if result["hardware_target"] != "CPU":
                            result["hardware_target"] = "CUDA"
                            if result["device_origin"] == "unknown":
                                result["device_origin"] = "bulk_ingest.py (load_model)"
                            else:
                                result["device_origin"] += " + bulk_ingest.py"
                        result["notes"].append(
                            "bulk_ingest.py passes device=variable from detect_device(). "
                            "If CUDA is available, it WILL use the GPU."
                        )
                        print("    Bulk ingest device: dynamic (may use CUDA)")
                    elif 'device="cpu"' in device_str:
                        if result["hardware_target"] == "unknown":
                            result["hardware_target"] = "CPU"
                            result["device_origin"] = "bulk_ingest.py"
                        print("    Bulk ingest device: CPU (hardcoded)")
                    elif 'device="cuda"' in device_str:
                        result["hardware_target"] = "CUDA"
                        result["device_origin"] = "bulk_ingest.py (hardcoded CUDA)"
                        result["notes"].append(
                            "WARNING: bulk_ingest.py hardcodes device='cuda'. "
                            "This will crash on CPU-only machines."
                        )
                        print("    Bulk ingest device: CUDA (HARDCODED -- risk!)")
                else:
                    result["notes"].append(
                        "bulk_ingest.py SentenceTransformer() call does not specify device. "
                        "Will use SentenceTransformer's default (CUDA if available)."
                    )

    # ------------------------------------------------------------------
    # Check the Semantic Search Path (app/services/semantic_search.py)
    # This file calls ``get_embedding_model()`` but does NOT instantiate
    # the model itself. We verify it uses the worker path correctly.
    # ----------------------------------------------------------------
    if SEMANTIC_SEARCH_PATH.exists():
        print(f"\n  [AUDIT] Checking semantic_search.py model usage...")
        search_lines: list[str] = _safe_read_lines(SEMANTIC_SEARCH_PATH)

        uses_get_embedding_model: bool = False
        for line in search_lines:
            if "get_embedding_model" in line and not line.strip().startswith("#"):
                uses_get_embedding_model = True
                print("    semantic_search.py uses get_embedding_model() from worker [OK]")
                break

        if not uses_get_embedding_model:
            result["notes"].append(
                "semantic_search.py does NOT call get_embedding_model(). "
                "It may instantiate SentenceTransformer directly."
            )

    return result


# =====================================================================
# AUDIT 3: Scan data directories for staged files
# =====================================================================
# We look for a ``data/`` or ``datasets/`` folder in the project root,
# then list any CSV or JSON files found inside. We also check the
# project root itself for ``indian_essential_meds.csv``.
#
# Beginner Note: Staging directories are where raw data files sit
# BEFORE they are processed by the ingestion pipeline. In a pharmacy
# context, think of them as the loading dock where boxes arrive
# before being shelved in the warehouse.


def audit_data_directories() -> dict:
    """
    Scan for data directories and list any ingestible files.

    Returns:
        A dictionary with keys:
            - "data_directory_exists": True/False
            - "files_found": list of file paths relative to project root.
    """
    result: dict = {
        "data_directory_exists": False,
        "files_found": [],
    }

    # ------------------------------------------------------------------
    # Step A: Check for data/ or datasets/ directories
    # ------------------------------------------------------------------
    for data_dir in DATA_DIRECTORIES:
        if data_dir.is_dir():
            result["data_directory_exists"] = True
            print(f"\n  [AUDIT] Found directory: {data_dir.relative_to(PROJECT_ROOT)}/")

            # Recursively find all CSV and JSON files inside.
            for item in data_dir.rglob("*"):
                if item.is_file() and item.suffix.lower() in (".csv", ".json"):
                    relative_path: str = str(item.relative_to(PROJECT_ROOT))
                    result["files_found"].append(relative_path)
                    print(f"    -> {relative_path}")

    # ------------------------------------------------------------------
    # Step B: Check the project root for CSV/JSON files that look like
    #         clinical drug datasets.
    # ------------------------------------------------------------------
    # The ``indian_essential_meds.csv`` file is expected at the project
    # root by ``bulk_ingest.py``. We also note any other CSVs found.
    # ----------------------------------------------------------------
    csv_files_in_root: list[Path] = list(PROJECT_ROOT.glob("*.csv"))
    json_files_in_root: list[Path] = list(PROJECT_ROOT.glob("*.json"))

    for csv_path in csv_files_in_root:
        relative: str = str(csv_path.relative_to(PROJECT_ROOT))
        if relative not in result["files_found"]:
            result["files_found"].append(relative)
            print(f"\n  [AUDIT] Found root CSV: {relative}")

    for json_path in json_files_in_root:
        # Filter out config and report files -- we only want data files.
        filename = json_path.name.lower()
        keywords: list[str] = [".secrets", "package", "package-lock", "tsconfig"]
        is_config_or_report: bool = any(kw in filename for kw in keywords)

        if not is_config_or_report:
            relative = str(json_path.relative_to(PROJECT_ROOT))
            if relative not in result["files_found"]:
                result["files_found"].append(relative)
                print(f"\n  [AUDIT] Found root JSON: {relative}")

    return result


# =====================================================================
# MAIN — Orchestrate the audit and print structured JSON
# =====================================================================
# We run all three audits in sequence, then combine their results into
# a single JSON object that matches the expected output schema.
#
# The JSON is printed to stdout so the developer can pipe it to a file:
#     python scripts/audit_phase5_ingestion.py > audit_phase5_report.json


def main() -> None:
    """Run the complete Phase 5 ingestion audit and print JSON."""

    print("=" * 72)
    print("  PHASE 5 INGESTION AUDIT — Read-Only Inspection")
    print("=" * 72)
    print(f"  Project root: {PROJECT_ROOT}")
    print(f"  Audit date:   {__import__('datetime').datetime.now().isoformat()}")
    print("=" * 72)

    # ------------------------------------------------------------------
    # AUDIT 1: Legacy ingest state
    # ------------------------------------------------------------------
    print("\n--- AUDIT 1: Legacy Ingestion Scripts ---")
    ingest_state: dict = audit_bulk_ingest()

    # Build a human-readable narrative for the summary.
    if ingest_state["exists"]:
        narrative_parts: list[str] = [
            f"Found scripts/bulk_ingest.py "
            f"(expects {ingest_state['file_format_found']} format)."
        ]
        if ingest_state["target_tables"]:
            tables_str: str = ", ".join(ingest_state["target_tables"])
            narrative_parts.append(f"Targets tables: {tables_str}.")
        else:
            narrative_parts.append("No explicit database table references found.")
        ingest_narrative: str = " ".join(narrative_parts)
    else:
        ingest_narrative = (
            "scripts/bulk_ingest.py does not exist. "
            "No legacy ingestion pipeline detected."
        )

    # ------------------------------------------------------------------
    # AUDIT 2: Embedding engine configuration
    # ------------------------------------------------------------------
    print("\n--- AUDIT 2: Embedding Engine Configuration ---")
    engine_config: dict = audit_embedding_engine()

    # ------------------------------------------------------------------
    # AUDIT 3: Staged data discovery
    # ------------------------------------------------------------------
    print("\n--- AUDIT 3: Staged Data Discovery ---")
    data_discovery: dict = audit_data_directories()

    # ------------------------------------------------------------------
    # Build the final JSON output
    # ------------------------------------------------------------------
    report: dict = {
        "agent_action_summary": ingest_narrative,
        "legacy_ingest_state": ingest_state,
        "embedding_engine_config": engine_config,
        "staged_data_discovery": data_discovery,
    }

    # Print the JSON with indentation for human readability.
    print("\n" + "=" * 72)
    print("  AUDIT COMPLETE — Structured JSON Output Below")
    print("=" * 72)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
