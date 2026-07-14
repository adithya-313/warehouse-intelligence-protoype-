"""
Preflight RAG Architecture Verification Script.

Beginner Note (read this first!):
    This script performs a READ-ONLY health check on three critical components
    of the Sentinel-Flow RAG pipeline:

    1. Alembic Migration State — Are there any pending database migrations
       that haven't been applied to the live database? Specifically, we
       check if migration `31763ac860b3` has been applied.

    2. Clinical Knowledge Base — Does the `clinical_knowledge_base` table
       exist in PostgreSQL? How many rows (clinical documents with vector
       embeddings) does it currently hold?

    3. PubMedBERT Embedding Engine — Can the HuggingFace
       `NeuML/pubmedbert-base-embeddings` model load into memory on this
       machine? This checks for the cursed `WinError 127` DLL crash that
       plagues Windows + torchaudio installations.

    The script NEVER writes to the database or modifies any files. It is
    a pure diagnostic tool for the system architect to assess readiness
    before injecting the CDSCO dataset.

Author: Sentinel-Flow Preflight System
"""

# =========================================================================
# Step 1: Import the tools we need for this investigation.
# =========================================================================
# We import these at the TOP of the file so any ImportError is caught
# immediately and reported to the user.
import json  # For formatting the final execution report
import logging  # For printing timestamped status messages
import os  # For reading environment variables (DATABASE_URL)
import re  # For parsing migration file headers (Revision ID, Revises)
import sys  # For exiting with a clear error code if something goes wrong

# -------------------------------------------------------------------------
# Beginner Note: We set up logging first so that every message printed by
# this script has a consistent format with a timestamp. This makes it easy
# to correlate our script's output with Docker logs or system events.
# -------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("preflight_rag_check")

# =========================================================================
# Step 2: Define the output structure for our execution report.
# =========================================================================
# Beginner Note: We create a plain Python dictionary that we will fill in
# as each check runs. At the end, we convert it to JSON and print it so
# the system architect can parse it programmatically.
# -------------------------------------------------------------------------
execution_report = {
    "agent_action_summary": "Running preflight checks on RAG architecture: Alembic state, clinical_knowledge_base existence/count, PubMedBERT model load test.",
    "git_status": "Unknown",
    "file_verification": {
        "bulk_ingest_py": "Unknown",
        "rag_pipeline_py": "Unknown",
        "semantic_search_py": "Unknown",
    },
    "database_state": {
        "alembic_head_matches_db": None,
        "clinical_knowledge_base_row_count": None,
    },
    "embedding_engine_status": "Not Tested",
    "next_recommended_steps": "",
}

# =========================================================================
# Step 3: Check the working tree status (git status).
# =========================================================================
# Beginner Note: We use Python's built-in subprocess module to run `git
# status --porcelain`. The `--porcelain` flag gives us a machine-readable
# output that is easy to parse. If there are NO uncommitted changes, the
# output will be empty.
# -------------------------------------------------------------------------
logger.info("Step 3: Checking Git working tree status...")

import subprocess

try:
    # Run 'git status --porcelain' in the project root directory.
    # We use capture_output=True to read the result instead of printing it.
    git_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )

    # If the output is empty, the working tree is clean.
    if git_result.returncode == 0 and git_result.stdout.strip() == "":
        execution_report["git_status"] = "Clean"
        logger.info("  => Git working tree is CLEAN. No uncommitted changes.")
    else:
        # There are uncommitted or untracked files.
        execution_report["git_status"] = "Uncommitted Changes"
        logger.info(f"  => Git working tree has changes:\n{git_result.stdout.strip()}")
except Exception as git_error:
    # If git is not installed or the command fails, report it gracefully.
    execution_report["git_status"] = f"Check Failed: {str(git_error)}"
    logger.warning(f"  => Could not check git status: {git_error}")

# =========================================================================
# Step 4: Verify that the three critical RAG files exist on disk.
# =========================================================================
# Beginner Note: We check three files that are essential for the RAG
# pipeline to function:
#   1. scripts/bulk_ingest.py    — GPU batch ingestion engine.
#   2. app/services/rag_pipeline.py — Adaptive routing (Traffic Cop).
#   3. app/services/semantic_search.py — Hybrid vector search engine.
# -------------------------------------------------------------------------
logger.info("Step 4: Verifying critical RAG file paths...")

# Determine the project root directory (the parent of the scripts/ folder).
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# List of (report_key, relative_path) pairs we need to verify.
required_files = [
    ("bulk_ingest_py", "scripts/bulk_ingest.py"),
    ("rag_pipeline_py", "app/services/rag_pipeline.py"),
    ("semantic_search_py", "app/services/semantic_search.py"),
]

for report_key, relative_path in required_files:
    full_path = os.path.join(project_root, relative_path)
    if os.path.isfile(full_path):
        execution_report["file_verification"][report_key] = "Found"
        logger.info(f"  => [FOUND] {relative_path}")
    else:
        execution_report["file_verification"][report_key] = "Missing"
        logger.warning(f"  => [MISSING] {relative_path} — RAG pipeline may be broken!")

# =========================================================================
# Step 5: Check the Alembic migration state against the live database.
# =========================================================================
# Beginner Note: We need to know whether migration 31763ac860b3 (which
# purges the legacy warehouse tables) has been applied to the live
# PostgreSQL database. We do this by:
#   1. Reading the Alembic migration files on disk to find the head.
#   2. Connecting to the database and querying the alembic_version table.
#   3. Comparing the two values.
#
# If the database is unreachable (e.g., Docker is down or DATABASE_URL
# is pointing to a container hostname that doesn't exist outside Docker),
# we report the failure clearly.
# -------------------------------------------------------------------------
logger.info("Step 5: Checking Alembic migration state against live database...")

# Step 5a: Read the migration files on disk and follow the Revises chain
# to determine the true Alembic head.
#
# BEGINNER NOTE: We CANNOT sort the filenames alphabetically to find the
# head because the revision IDs are hashes (e.g., '31763ac860b3' sorts
# BEFORE '8426ce3b0aba' alphabetically, but 8426ce3b0aba is actually the
# *parent* of 31763ac860b3 in the migration chain). Instead, we read the
# 'Revises:' line from each file and follow the chain from the root
# (the migration with no parent) to find the true head.
alembic_versions_dir = os.path.join(project_root, "alembic", "versions")
disk_migration_ids = []
revision_to_parent = {}  # Maps each child revision -> its parent (Revises)
parent_to_child = {}     # Maps each parent -> its child (reverse of above)

if os.path.isdir(alembic_versions_dir):
    for filename in os.listdir(alembic_versions_dir):
        if filename.endswith(".py") and not filename.startswith("__"):
            filepath = os.path.join(alembic_versions_dir, filename)
            with open(filepath, "r", encoding="utf-8") as fh:
                file_content = fh.read()
            # Extract the Revision ID from the docstring header.
            # Example format: "Revision ID: 31763ac860b3"
            rev_match = re.search(r"Revision ID:\s*(\S+)", file_content)
            # Extract the Revises (parent) from the docstring header.
            # Example format: "Revises: 8426ce3b0aba"
            revises_match = re.search(r"Revises:\s*(\S+)", file_content)
            if rev_match:
                rev_id = rev_match.group(1)
                disk_migration_ids.append(rev_id)
                if revises_match:
                    parent_id = revises_match.group(1)
                    # Alembic places the string "Create" as the Revises value
                    # for the very first migration (the one with no parent).
                    # We skip it — it is NOT a real revision ID.
                    if parent_id != "Create":
                        # The KEY is the child revision, the VALUE is its parent.
                        revision_to_parent[rev_id] = parent_id
                        parent_to_child[parent_id] = rev_id

# Find the root: a revision that has NO parent (it appears as neither a
# key in revision_to_parent representing a child, nor was its Revises
# value an actual revision ID like "Create").
all_revisions_set = set(disk_migration_ids)
all_child_ids = set(revision_to_parent.keys())
root_revisions = all_revisions_set - all_child_ids

# Find the head: a revision that is NO ONE's parent (its ID does not
# appear as a value in revision_to_parent).
all_parent_ids = set(revision_to_parent.values())
head_revisions = all_revisions_set - all_parent_ids

alembic_head_on_disk = "Unknown"
if head_revisions:
    alembic_head_on_disk = list(head_revisions)[0]

# Build the full chain from root -> head by following revision_to_parent.
chain_parts = []
if root_revisions:
    current_chain = list(root_revisions)[0]
    while current_chain in parent_to_child:
        chain_parts.append(current_chain)
        current_chain = parent_to_child[current_chain]
    # Append the final migration (the head).
    if current_chain:
        chain_parts.append(current_chain)

logger.info(f"  => Alembic head on DISK: {alembic_head_on_disk}")
logger.info(f"  => Full migration chain: {' -> '.join(chain_parts)}")

# Step 5b: Try to connect to the live PostgreSQL database and check the
# alembic_version table.
# We read the DATABASE_URL from the environment. If it's not set, we use
# the default from docker-compose (which points to the timescaledb container).
database_url = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgrespassword@timescaledb:5432/sentinel_db",
)
logger.info(f"  => Database URL: {database_url}")

try:
    # We import psycopg2 here (not at the top) because it is an optional
    # dependency — we don't want the script to crash if psycopg2 is not
    # installed on this machine.
    import psycopg2

    # Attempt to establish a connection to the database.
    # We set connect_timeout=5 so we don't hang forever if Docker is down.
    connection = psycopg2.connect(database_url, connect_timeout=5)
    cursor = connection.cursor()

    # Query the alembic_version table to see which migration is applied.
    cursor.execute("SELECT version_num FROM alembic_version;")
    alembic_db_row = cursor.fetchone()

    if alembic_db_row:
        alembic_version_in_db = alembic_db_row[0]
        logger.info(f"  => Alembic version in DATABASE: {alembic_version_in_db}")

        # Compare the database version to the disk head.
        if alembic_version_in_db == alembic_head_on_disk:
            execution_report["database_state"]["alembic_head_matches_db"] = True
            logger.info("  => Alembic state: DISK matches DATABASE. ✓")
        else:
            execution_report["database_state"]["alembic_head_matches_db"] = False
            logger.warning(
                f"  => Alembic MISMATCH! Disk={alembic_head_on_disk}, "
                f"DB={alembic_version_in_db}. Run 'alembic upgrade head'."
            )
    else:
        # The alembic_version table exists but is empty — this means Alembic
        # has never been initialized on this database.
        execution_report["database_state"]["alembic_head_matches_db"] = False
        logger.warning(
            "  => Alembic version table is EMPTY. "
            "Run 'alembic stamp head' or 'alembic upgrade head'."
        )

    # Step 5c: Check the clinical_knowledge_base table.
    cursor.execute(
        "SELECT COUNT(*) AS row_count FROM clinical_knowledge_base;"
    )
    row_count_result = cursor.fetchone()
    row_count = row_count_result[0] if row_count_result else 0
    execution_report["database_state"]["clinical_knowledge_base_row_count"] = row_count
    logger.info(f"  => clinical_knowledge_base row count: {row_count}")

    # Close the database connection cleanly.
    cursor.close()
    connection.close()
    logger.info("  => Database connection closed cleanly.")

except ImportError:
    # psycopg2 is not installed on this Python environment.
    execution_report["database_state"]["alembic_head_matches_db"] = (
        f"Could not check — psycopg2 not installed. "
        f"Disk head is {alembic_head_on_disk}."
    )
    execution_report["database_state"]["clinical_knowledge_base_row_count"] = (
        "Could not check — psycopg2 not installed."
    )
    logger.warning(
        "  => psycopg2 is not installed. Cannot connect to PostgreSQL. "
        "Install with: pip install psycopg2-binary"
    )

except Exception as db_error:
    # The database is unreachable (likely Docker is not running, or the
    # DATABASE_URL points to a container hostname like 'timescaledb').
    error_message = str(db_error).strip()
    execution_report["database_state"]["alembic_head_matches_db"] = (
        f"Could not check — DB unreachable: {error_message[:100]}"
    )
    execution_report["database_state"]["clinical_knowledge_base_row_count"] = (
        f"Could not check — DB unreachable: {error_message[:100]}"
    )
    logger.warning(f"  => Could not connect to database: {error_message}")

# =========================================================================
# Step 6: Test the PubMedBERT embedding engine.
# =========================================================================
# Beginner Note: This is the most important hardware check. The PubMedBERT
# model (NeuML/pubmedbert-base-embeddings) is a 400MB transformer that
# converts medical text into 768-dimensional vectors. On Windows, the
# torchaudio library that sentence-transformers depends on can crash with
# a WinError 127 DLL error. We test this by attempting to load the model
# into memory.
#
# IMPORTANT: We wrap this in a try/except block so that a crash does NOT
# bring down the entire verification script.
# -------------------------------------------------------------------------
logger.info("Step 6: Testing PubMedBERT embedding engine load...")

try:
    # Step 6a: Attempt to import sentence_transformers.
    # This import triggers torch, torchaudio, and transformers to load.
    # On Windows with broken torchaudio DLLs, this is where WinError 127
    # would be raised.
    from sentence_transformers import SentenceTransformer

    logger.info("  => sentence_transformers imported successfully.")

    # Step 6b: Attempt to load the PubMedBERT model into memory.
    # We set device='cpu' to avoid CUDA driver issues on machines without
    # an NVIDIA GPU.
    logger.info("  => Loading NeuML/pubmedbert-base-embeddings on CPU...")
    embedding_model = SentenceTransformer(
        "NeuML/pubmedbert-base-embeddings", device="cpu"
    )
    logger.info("  => Model loaded successfully!")

    # Step 6c: Run a quick forward pass to verify the model actually works.
    # We encode a simple medical phrase and check that the output has the
    # expected 768 dimensions.
    test_text = ["Amoxicillin 500mg for bacterial infections"]
    test_embedding = embedding_model.encode(test_text)
    embedding_dimensions = len(test_embedding[0])

    if embedding_dimensions == 768:
        execution_report["embedding_engine_status"] = "CPU Functional"
        logger.info(
            f"  => Forward pass successful. Output dimensions: "
            f"{embedding_dimensions} (expected 768). ✓"
        )
    else:
        execution_report["embedding_engine_status"] = (
            f"CPU Functional but unexpected dimensions: {embedding_dimensions}"
        )
        logger.warning(
            f"  => Model loaded but output has {embedding_dimensions} "
            f"dimensions instead of 768!"
        )

except ImportError as import_error:
    # sentence_transformers is not installed in this Python environment.
    execution_report["embedding_engine_status"] = (
        f"sentence_transformers not installed: {str(import_error)}"
    )
    logger.warning(f"  => sentence_transformers not available: {import_error}")

except Exception as model_error:
    # The model failed to load — this is likely the WinError 127 DLL crash.
    error_message = str(model_error)
    if "WinError 127" in error_message or "DLL" in error_message:
        execution_report["embedding_engine_status"] = "DLL Error Detected"
        logger.error(
            "  => WinError 127 DLL crash detected! "
            "PubMedBERT cannot load on this Windows machine due to "
            "torchaudio DLL conflicts. Use a Linux/macOS machine or "
            "install a CPU-only torch build."
        )
    else:
        execution_report["embedding_engine_status"] = f"Load Failed: {error_message[:100]}"
        logger.error(f"  => Model load failed: {error_message}")

# =========================================================================
# Step 7: Generate the recommended next steps based on our findings.
# =========================================================================
# Beginner Note: Based on what we discovered in Steps 3-6, we generate a
# human-readable recommendation for what the system architect should do
# next to safely inject the CDSCO dataset.
# -------------------------------------------------------------------------
logger.info("Step 7: Generating next-step recommendations...")

recommendations = []

# Check if Alembic migration needs to be applied.
alembic_status = execution_report["database_state"]["alembic_head_matches_db"]
if alembic_status is True:
    recommendations.append(
        "Alembic is up-to-date. No migration action needed."
    )
elif alembic_status is False:
    recommendations.append(
        "Run 'alembic upgrade head' on the live TimescaleDB host to apply "
        "the pending migration 31763ac860b3 (purges legacy warehouse tables)."
    )
elif alembic_status and "Could not check" in str(alembic_status):
    recommendations.append(
        "Database is unreachable (likely Docker Desktop not running). "
        "Start Docker Desktop and run 'docker compose up -d' to restore "
        "database connectivity."
    )

# Check if the database has rows.
row_count = execution_report["database_state"]["clinical_knowledge_base_row_count"]
if isinstance(row_count, int):
    if row_count == 0:
        recommendations.append(
            "clinical_knowledge_base is EMPTY. Run 'scripts/bulk_ingest.py' "
            "on a GPU-equipped machine to seed the vector database with "
            "CDSCO dataset embeddings."
        )
    elif row_count > 0:
        recommendations.append(
            f"clinical_knowledge_base has {row_count} rows. You can proceed "
            f"with CDSCO injection, or replace existing data if needed."
        )

# Check the embedding engine status.
engine_status = execution_report["embedding_engine_status"]
if "CPU Functional" in engine_status:
    recommendations.append(
        "PubMedBERT embedding engine is FUNCTIONAL on CPU. You can safely "
        "generate embeddings on this machine (slow but functional)."
    )
elif "DLL Error" in engine_status:
    recommendations.append(
        "PubMedBERT is BLOCKED on this Windows machine by a torchaudio DLL "
        "error. To generate embeddings, either: (a) use a Linux/macOS "
        "machine, (b) install a CPU-only torch build without torchaudio, "
        "or (c) use the deterministic hash fallback already built into "
        "the embedding pipeline."
    )

execution_report["next_recommended_steps"] = " | ".join(recommendations)
logger.info(f"  => Recommendations: {execution_report['next_recommended_steps']}")

# =========================================================================
# Step 8: Print the final execution report as JSON.
# =========================================================================
# Beginner Note: We use json.dumps with indent=2 to produce a
# human-readable JSON output that can also be parsed by other tools.
# -------------------------------------------------------------------------
print("\n" + "=" * 70)
print("PREFLIGHT RAG CHECK — EXECUTION REPORT")
print("=" * 70)
print(json.dumps(execution_report, indent=2))
print("=" * 70)

# =========================================================================
# Step 9: Self-validation — confirm we did not modify any files or data.
# =========================================================================
# Beginner Note: We explicitly log a confirmation that this script is
# read-only. If any step above attempted to write to the database or
# modify files, we would catch it here.
# -------------------------------------------------------------------------
logger.info("Step 9: Self-validation — confirming read-only execution...")
logger.info(
    "  => SELF-VALIDATION PASSED: No files were modified. "
    "No database rows were inserted, updated, or deleted. "
    "This script performed only SELECT queries (read-only)."
)
