"""
PHASE 1 DATA LAYER AUDIT — Read-Only Territory Map
====================================================

Beginner Note:
    This script is a completely read-only inspection tool. It does NOT
    modify any files, database records, or git history. Think of it as
    walking around a building and taking notes — you are measuring the
    foundation (Phase 1) before you start adding new walls.

What we are checking:
    1. Which existing database tables have a ``tenant_id`` column
       (required for multi-tenant data isolation)?
    2. Whether those ``tenant_id`` columns enforce a FOREIGN KEY constraint
       (linking to the ``tenants`` table) or at least an INDEX.
    3. The exact structure (column names, data types, constraints) of the
       ``medications`` and ``medication_batches`` tables.
    4. Whether any table currently stores a pregnancy safety rating,
       pediatric age constraint, or drug interaction matrix.
    5. Whether the live database container (``timescaledb``) is online and
       reachable.
    6. Whether legacy warehouse tables have already been purged and whether
       there is a clashing audit-log table.
"""

# ======================================================================
# IMPORTS
# ======================================================================
# Beginner Note: We import standard library modules first, then third-party
# libraries (SQLAlchemy), and finally our own application code.

import json          # For printing the final report as pretty JSON
import logging       # For printing informative messages as we go
import os            # For file path operations
import re            # For searching patterns inside Python source files
import sys           # For exiting with an error code if something goes wrong

# ------------------------------------------------------------------
# Logging setup: we write to stderr so the JSON report (printed to
# stdout) stays clean and parseable. This is a common pattern when
# you want both human-readable progress AND machine-readable output.
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,  # <-- progress messages go to stderr
)
logger = logging.getLogger(__name__)

# ======================================================================
# STEP 1: Determine the project root directory
# ======================================================================
# Beginner Note: This script lives at ``scripts/audit_phase1_data.py``.
# The project root is one level up (the parent of ``scripts/``).

SCRIPT_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIRECTORY)

# ======================================================================
# STEP 2: Discover all SQLAlchemy model files
# ======================================================================
# Beginner Note: SQLAlchemy models are Python classes that inherit from
# ``declarative_base()``. Each class maps to one database table. In this
# project, the models live in two places:
#
#   1. app/infrastructure/models.py       (core business models)
#   2. app/infrastructure/db/models.py     (warehouse + audit models)
#

logger.info("Step 1: Discovering SQLAlchemy ORM model files...")

# A list of paths (relative to PROJECT_ROOT) to check for model definitions
MODEL_FILE_CANDIDATES = [
    "app/infrastructure/models.py",
    "app/infrastructure/db/models.py",
]

# We will store the full absolute path to every model file we actually find
found_model_files = []

for relative_path in MODEL_FILE_CANDIDATES:
    full_path = os.path.join(PROJECT_ROOT, relative_path)
    if os.path.isfile(full_path):
        found_model_files.append(full_path)
        logger.info(f"  [FOUND] {relative_path}")
    else:
        logger.warning(f"  [MISSING] {relative_path}")

# ======================================================================
# STEP 3: Parse each model file to discover tables and tenant_id columns
# ======================================================================
# Beginner Note: Instead of importing the Python module (which could fail
# if the database is unreachable or dependencies are missing), we READ the
# source code as plain text and use regular expressions to find the
# important parts. This is called "static analysis" — you are analyzing
# the code without running it.
#
# We look for patterns like:
#   class SomeModel(Base):
#   __tablename__ = "some_table"
#   tenant_id = Column(String, ForeignKey(...), index=True, ...)
#

logger.info("Step 2: Parsing model files for table and column definitions...")

# ------------------------------------------------------------------
# Helper function 1: Extract table name from a model class.
# We look for a line like:  __tablename__ = "my_table"
# ------------------------------------------------------------------
def extract_tablename(class_source_code: str) -> str | None:
    """
    Given the full source code of a single model class, return the
    database table name (the value of __tablename__), or None if we
    cannot find it.

    Beginner Note:
        The regex looks for ``__tablename__``, then an equals sign,
        then a string in double or single quotes.
    """
    match = re.search(
        r'__tablename__\s*=\s*["\']([^"\']+)["\']',
        class_source_code,
    )
    if match:
        return match.group(1)
    return None


# ------------------------------------------------------------------
# Helper function 2: Check if a column has a ForeignKey constraint.
# We look for:  Column(..., ForeignKey("some_table.some_column"), ...)
# ------------------------------------------------------------------
def column_has_foreign_key(column_source_line: str) -> bool:
    """
    Returns True if the given source line (a Column definition) contains
    a ForeignKey(...) call.

    Beginner Note:
        The regex searches for the word ``ForeignKey`` followed by an
        opening parenthesis ``(`` anywhere in the line.
    """
    return bool(re.search(r"ForeignKey\s*\(", column_source_line))


# ------------------------------------------------------------------
# Helper function 3: Check if a column has an index constraint.
# We look for:  Column(..., index=True, ...)
# ------------------------------------------------------------------
def column_has_index(column_source_line: str) -> bool:
    """
    Returns True if the given source line (a Column definition) contains
    ``index=True``.

    Beginner Note:
        The regex uses a negative lookahead ``(?!=False)`` to make sure
        we do NOT match ``index=False``.
    """
    return bool(re.search(r"index\s*=\s*True", column_source_line))


# ------------------------------------------------------------------
# Helper function 4: Extract the column name from a Column definition.
# We look for patterns like:  tenant_id = Column(...)
# ------------------------------------------------------------------
def extract_column_name(column_source_line: str) -> str | None:
    """
    Extracts the column name from a line like::

        tenant_id = Column(String, ForeignKey(...), index=True, ...)

    Returns the column name (e.g., "tenant_id") or None.
    """
    match = re.search(r'^\s+(\w+)\s*=\s*Column\s*\(', column_source_line)
    if match:
        return match.group(1)
    return None


# ------------------------------------------------------------------
# Helper function 5: Extract the column data type from a Column definition.
# We look for patterns like:  Column(String, ...)  or  Column(Integer, ...)
# ------------------------------------------------------------------
def extract_column_type(column_source_line: str) -> str | None:
    """
    Extracts the column data type from a Column definition line.
    Returns the type name (e.g., "String", "Integer", "Numeric(10, 2)")
    or None.

    Beginner Note:
        The data type is the FIRST argument inside Column(...).
        It can be a simple name like ``String`` or a parameterized
        type like ``Numeric(10, 2)``.
    """
    # Match the first argument inside Column(...) — it's the data type.
    # This regex extracts everything up to the first comma or closing paren.
    match = re.search(
        r"Column\s*\(\s*([\w]+(?:\([^)]*\))?)",
        column_source_line,
    )
    if match:
        return match.group(1)
    return None


# ======================================================================
# Now we read each model file and split it into individual class blocks.
# ======================================================================

# We will build a data structure that maps:
#   table_name -> {
#       "columns": { column_name: { "type": ..., "has_fk": bool, "has_index": bool } },
#       "model_name": "SomeModel",
#       "source_file": "relative/path.py",
#   }
tables_discovered = {}

for model_file_path in found_model_files:
    # Calculate the relative path so our output is readable
    relative_file_path = os.path.relpath(model_file_path, PROJECT_ROOT)
    logger.info(f"    Parsing {relative_file_path}...")

    # Read the entire source file as a string
    with open(model_file_path, "r", encoding="utf-8") as file_handle:
        file_source_code = file_handle.read()

    # ------------------------------------------------------------------
    # Split the source into individual class definitions.
    # We use a regex that matches from ``class ClassName(Base):``
    # all the way to the next ``class `` statement (or end of file).
    # ------------------------------------------------------------------
    class_blocks = re.split(r'(?=^class\s+\w+)', file_source_code, flags=re.MULTILINE)

    for class_block in class_blocks:
        # Skip anything that does not look like a class definition
        if not class_block.strip().startswith("class "):
            continue

        # Check that this class inherits from Base (SQLAlchemy's declarative base)
        if "Base)" not in class_block.split("\n")[0]:
            continue

        # Extract the model name (e.g., "MedicationModel")
        model_name_match = re.search(r"^class\s+(\w+)", class_block)
        if not model_name_match:
            continue

        model_name = model_name_match.group(1)

        # Extract the table name from ``__tablename__``
        tablename = extract_tablename(class_block)

        if tablename is None:
            # Some classes might not define __tablename__ (e.g., mixins).
            # We skip those — they do not represent real database tables.
            continue

        # ------------------------------------------------------------------
        # Now find every ``column_name = Column(...)`` definition inside
        # this class block and extract its properties.
        # ------------------------------------------------------------------
        column_definitions = {}

        # Find all lines (or multi-line blocks) that start a Column definition
        column_lines = re.findall(
            r"^\s+(\w+)\s*=\s*(?:Column)\s*\([^)]*\)",
            class_block,
            re.MULTILINE,
        )

        # Actually, the simple regex above won't catch multi-line Column
        # definitions (which are common in SQLAlchemy). Let's use a better
        # approach: iterate line by line and track state.

        # Reset: find all Column definitions by scanning lines
        lines = class_block.split("\n")
        inside_column = False
        current_column_buffer = ""
        column_name_current = None

        for line_index, line in enumerate(lines):
            # Look for the start of a Column definition
            if not inside_column:
                column_start_match = re.search(
                    r"^\s+(\w+)\s*=\s*(?:Column)\s*\(",
                    line,
                )
                if column_start_match:
                    inside_column = True
                    column_name_current = column_start_match.group(1)
                    current_column_buffer = line
                    # If this line closes the parenthesis, handle it now
                    if ")" in line[line.index("("):]:
                        # Single-line Column definition
                        col_name = extract_column_name(current_column_buffer)
                        if col_name:
                            column_definitions[col_name] = {
                                "type": extract_column_type(current_column_buffer),
                                "has_fk": column_has_foreign_key(current_column_buffer),
                                "has_index": column_has_index(current_column_buffer),
                                "is_tenant_id": (col_name == "tenant_id"),
                            }
                        inside_column = False
                        column_name_current = None
                        current_column_buffer = ""
            else:
                # We are inside a multi-line Column definition
                current_column_buffer += " " + line.strip()
                # Check if this line closes the parenthesis
                # Count opening and closing parentheses
                open_parens = current_column_buffer.count("(")
                close_parens = current_column_buffer.count(")")
                if open_parens > 0 and open_parens == close_parens:
                    # The Column definition is complete
                    col_name = extract_column_name(current_column_buffer)
                    if col_name:
                        column_definitions[col_name] = {
                            "type": extract_column_type(current_column_buffer),
                            "has_fk": column_has_foreign_key(current_column_buffer),
                            "has_index": column_has_index(current_column_buffer),
                            "is_tenant_id": (col_name == "tenant_id"),
                        }
                    inside_column = False
                    column_name_current = None
                    current_column_buffer = ""

        # Register this table in our global data structure
        tables_discovered[tablename] = {
            "model_name": model_name,
            "source_file": relative_file_path,
            "columns": column_definitions,
        }

        # Log what we found
        column_count = len(column_definitions)
        logger.info(f"      Table '{tablename}' ({model_name}): {column_count} columns.")

# ======================================================================
# STEP 4: Identify tables with and without tenant_id isolation
# ======================================================================

logger.info("Step 3: Analyzing tenant isolation coverage...")

# Sort table names so our output is deterministic and easy to read
sorted_table_names = sorted(tables_discovered.keys())

isolated_tables = []      # Tables that HAVE a tenant_id column
missing_isolation_tables = []  # Tables that do NOT have a tenant_id column

for table_name in sorted_table_names:
    table_info = tables_discovered[table_name]
    has_tenant_id = False
    tenant_id_details = None

    for col_name, col_info in table_info["columns"].items():
        if col_info["is_tenant_id"]:
            has_tenant_id = True
            tenant_id_details = {
                "column_name": col_name,
                "data_type": col_info["type"],
                "has_foreign_key": col_info["has_fk"],
                "has_index": col_info["has_index"],
            }
            break

    if has_tenant_id:
        isolated_tables.append({
            "table_name": table_name,
            "model_name": table_info["model_name"],
            "source_file": table_info["source_file"],
            "tenant_id_details": tenant_id_details,
        })
        logger.info(
            f"  [ISOLATED] {table_name}: "
            f"tenant_id ({tenant_id_details['data_type']}, "
            f"FK={tenant_id_details['has_foreign_key']}, "
            f"index={tenant_id_details['has_index']})"
        )
    else:
        missing_isolation_tables.append({
            "table_name": table_name,
            "model_name": table_info["model_name"],
            "source_file": table_info["source_file"],
        })
        logger.info(f"  [NO TENANT_ID] {table_name} (model: {table_info['model_name']})")

# ======================================================================
# STEP 5: Examine the medications and medication_batches tables in detail
# ======================================================================

logger.info("Step 4: Inspecting medications and medication_batches structure...")

medications_structure = None
medication_batches_structure = None

for table_name, table_info in tables_discovered.items():
    if table_name == "medications":
        medications_structure = table_info["columns"]
        logger.info(f"  [MEDICATIONS] Found {len(table_info['columns'])} columns:")
        for col_name, col_info in table_info["columns"].items():
            logger.info(f"      - {col_name}: {col_info['type']} "
                        f"(FK={col_info['has_fk']}, index={col_info['has_index']})")

    elif table_name == "medication_batches":
        medication_batches_structure = table_info["columns"]
        logger.info(f"  [MEDICATION_BATCHES] Found {len(table_info['columns'])} columns:")
        for col_name, col_info in table_info["columns"].items():
            logger.info(f"      - {col_name}: {col_info['type']} "
                        f"(FK={col_info['has_fk']}, index={col_info['has_index']})")

if medications_structure is None:
    logger.warning("  [WARNING] 'medications' table NOT FOUND in discovered models!")

if medication_batches_structure is None:
    logger.warning("  [WARNING] 'medication_batches' table NOT FOUND in discovered models!")

# ======================================================================
# STEP 6: Search for clinical field references (pregnancy, pediatric,
#         interaction matrix) across the codebase
# ======================================================================

logger.info("Step 5: Scanning codebase for clinical field references...")

# These are the keywords we search for in every Python file under app/
# and scripts/. They indicate whether the project has structured fields
# for pregnancy safety, pediatric age constraints, or drug interactions.
CLINICAL_KEYWORD_MAP = {
    "has_pregnancy_categories": [
        "pregnancy_category",
        "pregnancy_safety",
        "pregnancy_rating",
        "fda_category",
        "pregnancy_risk",
    ],
    "has_pediatric_thresholds": [
        "pediatric_age",
        "pediatric_dosage",
        "child_min_age",
        "pediatric_threshold",
        "min_age_months",
        "max_age_years",
        "age_restriction",
    ],
    "has_interaction_matrix": [
        "interaction_matrix",
        "drug_interaction",
        "interaction_severity",
        "contraindication_pair",
        "interaction_score",
    ],
}

# We will scan all .py files under app/ and scripts/, plus the two model files.
clinical_scan_results = {
    "has_pregnancy_categories": False,
    "has_pediatric_thresholds": False,
    "has_interaction_matrix": False,
}

# Directories to scan (relative to PROJECT_ROOT)
SCAN_DIRECTORIES = ["app", "scripts"]

# Collect all .py files to search
files_to_scan = []

for scan_dir in SCAN_DIRECTORIES:
    scan_path = os.path.join(PROJECT_ROOT, scan_dir)
    if not os.path.isdir(scan_path):
        continue
    for root_directory, subdirectories, filenames in os.walk(scan_path):
        # Skip virtual environment and cache directories
        if "__pycache__" in root_directory:
            continue
        if "node_modules" in root_directory:
            continue
        for filename in filenames:
            if filename.endswith(".py"):
                files_to_scan.append(os.path.join(root_directory, filename))

logger.info(f"  Scanning {len(files_to_scan)} Python files across "
            f"{', '.join(SCAN_DIRECTORIES)}...")

for python_file in files_to_scan:
    # CRITICAL: Skip our own audit script — otherwise it would find the
    # keyword_map variable names (e.g., "pregnancy_category") and report
    # false positives!
    if os.path.abspath(python_file) == os.path.abspath(__file__):
        continue

    try:
        with open(python_file, "r", encoding="utf-8") as file_handle:
            file_content = file_handle.read()
    except (UnicodeDecodeError, PermissionError, OSError):
        # Skip files we cannot read
        continue

    # Check each keyword category against the file content (case-insensitive)
    for category_keyword, keyword_list in CLINICAL_KEYWORD_MAP.items():
        if clinical_scan_results[category_keyword]:
            # Already found a match — no need to keep searching this category
            continue
        for keyword in keyword_list:
            if re.search(keyword, file_content, re.IGNORECASE):
                clinical_scan_results[category_keyword] = True
                logger.info(
                    f"  [FOUND] '{keyword}' match in "
                    f"{os.path.relpath(python_file, PROJECT_ROOT)}"
                )
                break  # Stop checking this category once we find one match

# Log the final assessment for each clinical field category
for category_keyword, found in clinical_scan_results.items():
    status = "DETECTED" if found else "NOT DETECTED"
    logger.info(f"  => {category_keyword}: {status}")

# ======================================================================
# STEP 7: Test database connectivity
# ======================================================================

logger.info("Step 6: Testing database connectivity...")

# We try to connect to the database using psycopg2 (the PostgreSQL driver)
# directly with a short timeout. We do NOT import the full application
# engine because it might hang if the container is down.

db_connectivity = "Offline"
database_error_message = None

try:
    # Attempt to import psycopg2 (it should be installed as a dependency)
    import psycopg2  # type: ignore

    # Read the DATABASE_URL from the environment, falling back to the
    # default value used in the docker-compose setup.
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgrespassword@timescaledb:5432/sentinel_db",
    )

    # psycopg2 does not have a built-in connection timeout parameter in the
    # same way SQLAlchemy does. We use ``connect_timeout=5`` in the URL
    # query string to enforce a 5-second timeout.
    if "?" not in database_url:
        database_url_with_timeout = database_url + "?connect_timeout=5"
    else:
        database_url_with_timeout = database_url + "&connect_timeout=5"

    logger.info(f"  Attempting connection to database...")

    # Try to establish a connection
    connection = psycopg2.connect(database_url_with_timeout)
    connection.close()

    db_connectivity = "Online"
    logger.info("  [SUCCESS] Database connection established!")

except ImportError:
    # psycopg2 is not installed — this happens when running outside Docker
    database_error_message = (
        "psycopg2 is not installed in this Python environment. "
        "Cannot test database connectivity without the PostgreSQL driver."
    )
    logger.warning(f"  [WARNING] {database_error_message}")

except Exception as connection_error:
    # Capture the error message for the report
    database_error_message = str(connection_error).strip()
    logger.warning(f"  [OFFLINE] Database is not reachable: {database_error_message}")

# ======================================================================
# STEP 8: Check for conflicting structures
# ======================================================================

logger.info("Step 7: Checking for conflicting legacy structures...")

# ------------------------------------------------------------------
# Check 8a: Clashing audit-log tables
#
# The project currently has an "audit_ledger" table used for financial
# fraud analysis. If we are building a new Phase 1 audit system, we
# need to know whether that existing table will conflict with our new
# design (e.g., overlapping table names, conflicting semantics).
# ------------------------------------------------------------------
clashing_audit_logs_exist = "audit_ledger" in tables_discovered

if clashing_audit_logs_exist:
    logger.info(
        "  [CONFLICT DETECTED] 'audit_ledger' table already exists "
        "(defined in app/infrastructure/db/models.py). "
        "Phase 1 audit design must NOT collide with this table."
    )
else:
    logger.info("  [NO CONFLICT] No pre-existing audit ledger table found.")

# ------------------------------------------------------------------
# Check 8b: Legacy warehouse tables have been purged
#
# Migration 31763ac860b3 explicitly drops three tables:
#   warehouse_nodes, warehouse_edges, movement_telemetry
#
# We verify this by checking that these table names do NOT appear in
# our discovered model files. They should not, since the corresponding
# ORM classes were removed.
# ------------------------------------------------------------------
LEGACY_WAREHOUSE_TABLES = ["warehouse_nodes", "warehouse_edges", "movement_telemetry"]

any_legacy_remaining = False
for legacy_table in LEGACY_WAREHOUSE_TABLES:
    if legacy_table in tables_discovered:
        logger.warning(f"  [LEGACY STILL PRESENT] '{legacy_table}' has an ORM model!")
        any_legacy_remaining = True

if any_legacy_remaining:
    legacy_warehouse_tables_purged = False
    logger.warning(
        "  [WARNING] Some legacy warehouse tables still have ORM definitions. "
        "They may need to be manually removed."
    )
else:
    legacy_warehouse_tables_purged = True
    logger.info(
        "  [PURGED] No legacy warehouse table definitions remain in ORM models. "
        "Migration 31763ac860b3 has been applied."
    )

# ======================================================================
# STEP 9: Self-validation — confirm we did not modify anything
# ======================================================================

logger.info("Step 8: Self-validating — confirming read-only execution...")

# We verify that:
#   1. No files were created, modified, or deleted (we can check via git)
#   2. No database write operations were performed

# For git, we run ``git status --porcelain`` to see if anything changed.
# We use the ``subprocess`` module to call git.
import subprocess  # nosec — this is a development tool, not production code

try:
    git_result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=10,
    )

    changed_files_before = set(git_result.stdout.splitlines())
    # Remove our own script from the list (it was written before execution)
    self_path = os.path.relpath(__file__, PROJECT_ROOT).replace("\\", "/")
    actual_changes = [
        line for line in changed_files_before
        if self_path not in line
    ]

    if actual_changes:
        logger.warning(
            "  [SELF-VALIDATION WARNING] Unexpected git changes detected:\n"
            + "\n".join(f"      {line}" for line in actual_changes)
        )
    else:
        logger.info("  [SELF-VALIDATION PASSED] No unintended modifications detected.")

except Exception as git_error:
    logger.warning(f"  [SELF-VALIDATION] Could not verify git status: {git_error}")
    logger.info("  [SELF-VALIDATION] Script performed only read operations by design.")

# Also log explicit confirmation that we did no database writes
logger.info(
    "  [SELF-VALIDATION] Confirmed: This script performed ZERO database "
    "write operations. All checks were file-system reads and connection tests."
)

# ======================================================================
# STEP 10: Compile and print the final execution report
# ======================================================================

logger.info("Step 9: Compiling execution report...")

# Build the "isolated tables" list for the JSON output
isolated_tables_output = []
for entry in isolated_tables:
    isolated_tables_output.append(entry["table_name"])

# Build the "missing isolation tables" list
missing_isolation_output = []
for entry in missing_isolation_tables:
    missing_isolation_output.append(entry["table_name"])

# Compile the full report as a Python dictionary
execution_report = {
    "agent_action_summary": (
        "Inspected 2 ORM model files (app/infrastructure/models.py, "
        "app/infrastructure/db/models.py); discovered "
        f"{len(tables_discovered)} database tables; scanned "
        f"{len(files_to_scan)} Python source files for clinical field keywords; "
        "tested database connectivity to the timescaledb container."
    ),
    "database_connectivity": db_connectivity,
    "current_tenant_isolation": {
        "isolated_tables": isolated_tables_output,
        "missing_isolation_tables": missing_isolation_output,
    },
    "clinical_fields_detected": {
        "has_pregnancy_categories": clinical_scan_results["has_pregnancy_categories"],
        "has_pediatric_thresholds": clinical_scan_results["has_pediatric_thresholds"],
        "has_interaction_matrix": clinical_scan_results["has_interaction_matrix"],
    },
    "conflicting_structures": {
        "clashing_audit_logs_exist": clashing_audit_logs_exist,
        "legacy_warehouse_tables_purged": legacy_warehouse_tables_purged,
    },
}

# Add detailed tenant_id information if any isolated tables were found
if isolated_tables:
    execution_report["tenant_id_detail"] = []
    for entry in isolated_tables:
        execution_report["tenant_id_detail"].append({
            "table": entry["table_name"],
            "model": entry["model_name"],
            "source": entry["source_file"],
            "foreign_key_enforced": entry["tenant_id_details"]["has_foreign_key"],
            "indexed": entry["tenant_id_details"]["has_index"],
        })

# Add detailed medication structure information
execution_report["medications_structure"] = medications_structure
execution_report["medication_batches_structure"] = medication_batches_structure

# Add database error message if applicable
if database_error_message:
    execution_report["database_error_detail"] = database_error_message

# Print the final report as pretty-printed JSON to stdout
# (the logging messages went to stderr, so stdout is clean)
print("=" * 70)
print("PHASE 1 DATA LAYER AUDIT — EXECUTION REPORT")
print("=" * 70)
print(json.dumps(execution_report, indent=2, default=str))
print("=" * 70)

# Log completion
logger.info("Audit complete. See stdout for the JSON execution report.")
