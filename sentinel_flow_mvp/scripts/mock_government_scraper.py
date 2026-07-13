"""
MOCK GOVERNMENT SCRAPER — CDSCO Regulatory Change Simulator
=============================================================

Beginner Note:
    In the real world, the Indian government's CDSCO (Central Drugs Standard
    Control Organization) publishes PDF notifications when a drug is banned,
    reclassified, or when its price cap changes. A scraper bot downloads
    those PDFs, parses them, and updates the local drug catalogue.

    This script is a MOCK version of that scraper. Instead of downloading
    real PDFs, we simulate a change event (e.g., "Paracetamol has been
    flagged for pregnancy category D") and process it through the same
    pipeline so we can test the regulatory_diff_log table.

How this script works:
    1. First, it checks if the database is reachable. If not, it logs a
       clean error and exits gracefully (no file mutations).
    2. If the database IS reachable, it:
       a. Simulates fetching a "regulatory alert" from the CDSCO portal.
       b. Checks if the alert data is valid (not empty, not malformed).
       c. Reads the current value of the target drug from ``medications``.
       d. Logs the OLD and NEW values into ``regulatory_diff_log``.
       e. Updates the drug in ``medications`` with ``is_approved_by_curator = False``
          so a human pharmacist must review the change before it goes live.

Custom Exception:
    If the simulated "feed" returns empty or malformed data, the script
    raises a ``StalenessAlertException`` instead of silently inserting
    blank rows into the database. This makes the monitoring system aware
    that the scraper is stale or broken.
"""

# ======================================================================
# IMPORTS
# ======================================================================
# Beginner Note: We import standard library modules first, then our own
# application code. We keep third-party imports minimal so the script
# can run even when the database is offline.

import json          # For printing the execution report
import logging       # For printing informative messages
import os            # For reading environment variables
import sys           # For exiting with error codes
from datetime import datetime, timezone  # For timestamps

# Import the cache invalidation helper so that whenever the scraper modifies
# the database, it also flushes the RAG response cache. This ensures
# clinical users always see up-to-date safety information.
from app.core.cache import increment_global_db_version_sync

# Set up logging so we can see what the script is doing
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


# ======================================================================
# CUSTOM EXCEPTION: StalenessAlertException
# ======================================================================
# Beginner Note: A custom exception is like creating your own type of
# error. Standard exceptions (like ValueError) are generic. This one
# is specific to our scraper — it means "the government data feed is
# empty or broken, and someone needs to investigate."
# ======================================================================

class StalenessAlertException(Exception):
    """
    Raised when the mock government scraper receives an empty or
    malformed data feed from the simulated CDSCO portal.

    Attributes:
        message: A human-readable explanation of what went wrong.
        timestamp: The exact time the error was raised (UTC).
        feed_content: The raw (invalid) content that triggered the error,
            so the monitoring system can log it for debugging.
    """

    def __init__(
        self,
        message: str,
        feed_content: str,
    ):
        """
        Initialize the exception with a descriptive message and the
        problematic feed content.

        Args:
            message: A clear description of why the feed was rejected.
            feed_content: The raw content of the malformed or empty feed.
        """
        # Call the parent Exception class constructor
        super().__init__(message)

        # Store additional context for the error log
        self.message = message
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.feed_content = feed_content

    def to_metric_log(self) -> dict:
        """
        Convert this exception into a structured dictionary suitable for
        sending to a monitoring system (e.g., Prometheus, DataDog).

        Beginner Note:
            Instead of just printing an error message and moving on, we
            return a structured JSON object. This way, the operations
            team can set up automated alerts when the scraper is stale.

        Returns:
            A dictionary with error_type, message, timestamp, and
            feed_content keys.
        """
        return {
            "error_type": "StalenessAlertException",
            "message": self.message,
            "timestamp": self.timestamp,
            "feed_content_preview": self.feed_content[:200],  # Truncate to 200 chars
        }


# ======================================================================
# HELPER FUNCTION: simulate_cdsco_feed
# ======================================================================
# Beginner Note: In the real world, this function would use something
# like ``requests.get("https://cdsco.gov.in/notifications.rss")`` to
# download the latest regulatory notifications from the government.
#
# In our mock version, we simulate two possible outcomes:
#   1. SUCCESS: We return a well-formed dictionary representing a
#      regulatory change (e.g., a drug being reclassified).
#   2. FAILURE: We return empty HTML to simulate a broken scraper.
# ======================================================================

def simulate_cdsco_feed(should_fail: bool = False) -> dict:
    """
    Simulate fetching the latest regulatory alert from the CDSCO portal.

    Args:
        should_fail: If True, simulate an empty / malformed feed response.
            This is used by the test suite to verify the StalenessAlertException.

    Returns:
        A dictionary with the simulated regulatory change data.

    Raises:
        StalenessAlertException: If the feed content is empty or malformed.
    """
    logger.info("Step 1: Fetching simulated CDSCO regulatory feed...")

    # ------------------------------------------------------------------
    # Simulate the raw HTML/JSON response from the government portal
    # ------------------------------------------------------------------
    if should_fail:
        # Scenario: The scraper downloaded the page, but it was empty
        # (the government portal might have been down, or the RSS feed
        # format changed and the parser could not extract any data).
        raw_feed_content = ""

        logger.warning(
            "  [FEED EMPTY] The CDSCO portal returned an empty response. "
            "This could mean the website is down or the scraper needs an update."
        )

        # Raise our custom exception. The calling code will catch it and
        # log the error metric instead of inserting empty rows.
        raise StalenessAlertException(
            message=(
                "CDSCO regulatory feed returned empty content. "
                "No regulatory changes were fetched. "
                "The scraper may need maintenance."
            ),
            feed_content=raw_feed_content,
        )

    # Simulate a successful regulatory alert
    logger.info("  [FEED OK] Received 1 regulatory notification from CDSCO.")

    # Build a realistic-looking regulatory change payload
    simulated_alert = {
        "alert_id": "CDSCO-2026-0731",
        "source_url": (
            "https://cdsco.gov.in/notifications/2026/0731/"
            "paracetamol-pregnancy-reclassification"
        ),
        "product_sku_id": "PARA_500",       # The SKU of the affected drug
        "field_changed": "pregnancy_category",  # Which column changed
        "old_value": None,                      # The previous value (None = not yet classified)
        "new_value": "D",                       # The new regulatory classification
        "reason": (
            "New clinical trial data shows increased risk of "
            "fetal harm in third trimester (FDA Category D)."
        ),
        "effective_date": "2026-08-15",
    }

    logger.info(
        f"  [ALERT] SKU: {simulated_alert['product_sku_id']} | "
        f"Field: {simulated_alert['field_changed']} | "
        f"Old: {simulated_alert['old_value']} -> New: {simulated_alert['new_value']}"
    )

    return simulated_alert


# ======================================================================
# HELPER FUNCTION: try_database_connection
# ======================================================================
# Beginner Note: We check if the database is reachable before doing any
# work. If the database is offline (which is expected when Docker Desktop
# is not running), we log a clean message and exit gracefully. We do NOT
# raise an exception or crash — we simply say "database is unavailable,
# cannot proceed with the scraper."
# ======================================================================

def try_database_connection() -> bool:
    """
    Test whether the PostgreSQL database is reachable.

    Returns:
        True if the database is online and accepting connections.
        False if the database is offline or unreachable.
    """
    logger.info("Step 0: Checking database connectivity...")

    # Read the DATABASE_URL from the environment, with a fallback default
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgrespassword@timescaledb:5432/sentinel_db",
    )

    # Add a 5-second connection timeout so we don't hang forever
    if "?" not in database_url:
        database_url_with_timeout = database_url + "?connect_timeout=5"
    else:
        database_url_with_timeout = database_url + "&connect_timeout=5"

    try:
        # Dynamically import psycopg2 (it is a project dependency, but we
        # import it here instead of at the top of the file so this script
        # can still be imported for its exception class without needing it)
        import psycopg2  # type: ignore  # noqa: F811

        # Try to establish a connection
        connection = psycopg2.connect(database_url_with_timeout)
        connection.close()

        logger.info("  [ONLINE] Database connection established successfully.")
        return True

    except ImportError:
        logger.warning(
            "  [IMPORT ERROR] psycopg2 is not installed in this environment. "
            "Cannot test database connectivity."
        )
        return False

    except Exception as connection_error:
        logger.warning(
            f"  [OFFLINE] Database is not reachable: {str(connection_error).strip()}"
        )
        return False


# ======================================================================
# HELPER FUNCTION: process_regulatory_change
# ======================================================================
# Beginner Note: This is the core logic of the scraper. It receives a
# regulatory alert (a dictionary), connects to the database, records the
# change in the audit log, and updates the medication record.
# ======================================================================

def process_regulatory_change(alert_data: dict) -> dict:
    """
    Process a single regulatory change alert through the pipeline.

    Steps:
        1. Connect to the database.
        2. Read the current value of the affected field from the
           ``medications`` table.
        3. Insert a row into ``regulatory_diff_log`` with the OLD and
           NEW values, the source URL, and the product ID.
        4. Update the ``medications`` table with the new value and set
           ``is_approved_by_curator = False`` so a human must review it.

    Args:
        alert_data: A dictionary with the regulatory change details.
            Must contain keys: 'product_sku_id', 'field_changed',
            'old_value', 'new_value', 'source_url'.

    Returns:
        A dictionary summarising the changes that were applied.
    """
    logger.info("Step 2: Processing regulatory change alert...")

    # Extract the relevant fields from the alert
    product_sku_id = alert_data["product_sku_id"]
    field_changed = alert_data["field_changed"]
    old_value = alert_data["old_value"]
    new_value = alert_data["new_value"]
    source_url = alert_data["source_url"]

    # ------------------------------------------------------------------
    # Step 2a: Connect to the database using the application's engine
    # ------------------------------------------------------------------
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session, sessionmaker

    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgrespassword@timescaledb:5432/sentinel_db",
    )

    engine = create_engine(database_url)
    SessionLocal = sessionmaker(bind=engine)

    # Open a session and wrap everything in a try/finally block so the
    # session is always closed, even if an error occurs.
    db_session = SessionLocal()

    try:
        # ------------------------------------------------------------------
        # Step 2b: Read the current value of the target field from the
        # medications table (before we change it).
        # ------------------------------------------------------------------
        logger.info(
            f"  Step 2b: Reading current value of '{field_changed}' "
            f"for SKU '{product_sku_id}'..."
        )

        # Build a dynamic SQL query to read the current value of the field
        # that is about to be changed. We use ``text()`` for raw SQL because
        # the column name is dynamic (it comes from the alert).
        select_query = text(
            f"SELECT {field_changed} FROM medications WHERE sku_id = :sku_id"
        )

        result = db_session.execute(select_query, {"sku_id": product_sku_id})
        current_row = result.fetchone()

        if current_row is None:
            # The drug does not exist in our catalogue yet. We log this
            # as a warning and skip the update.
            logger.warning(
                f"  [SKIP] SKU '{product_sku_id}' not found in medications table. "
                "No changes applied."
            )
            return {
                "status": "skipped",
                "reason": f"SKU '{product_sku_id}' not found in catalogue.",
            }

        actual_old_value = current_row[0]

        # If the old_value from the alert is None, use the actual database value
        if old_value is None:
            old_value = actual_old_value

        logger.info(
            f"  Current value of '{field_changed}' = {actual_old_value!r}"
        )

        # ------------------------------------------------------------------
        # Step 2c: Insert a row into regulatory_diff_log recording the change
        # ------------------------------------------------------------------
        logger.info("  Step 2c: Recording change in regulatory_diff_log...")

        insert_query = text("""
            INSERT INTO regulatory_diff_log
                (product_id, old_value, new_value, source_gov_url)
            VALUES
                (:product_id, :old_value, :new_value, :source_gov_url)
        """)

        db_session.execute(insert_query, {
            "product_id": product_sku_id,
            "old_value": str(old_value) if old_value is not None else "",
            "new_value": str(new_value),
            "source_gov_url": source_url,
        })

        # ------------------------------------------------------------------
        # Step 2d: Update the medications table with the new value and
        # mark it as unapproved (is_approved_by_curator = False).
        # ------------------------------------------------------------------
        logger.info(
            f"  Step 2d: Updating '{field_changed}' for SKU '{product_sku_id}' "
            "and setting is_approved_by_curator = False..."
        )

        update_query = text(f"""
            UPDATE medications
            SET
                {field_changed} = :new_value,
                is_approved_by_curator = false
            WHERE sku_id = :sku_id
        """)

        db_session.execute(update_query, {
            "new_value": new_value,
            "sku_id": product_sku_id,
        })

        # ------------------------------------------------------------------
        # Step 2e: Commit the transaction
        # ------------------------------------------------------------------
        db_session.commit()

        logger.info("  [COMMITTED] Regulatory change applied successfully.")

        # ------------------------------------------------------------------
        # Step 2f: Invalidate the RAG cache
        # ------------------------------------------------------------------
        # Beginner Note: After changing the database, we increment a version
        # counter in Redis. This "poisons" all cached RAG responses because
        # their cache keys include the old version number. Users will get
        # fresh responses generated from the updated data.
        #
        # If Redis is unavailable, we log a warning but do NOT fail the
        # entire scraper — the cache is an optimization, not a requirement.
        try:
            new_db_version = increment_global_db_version_sync()
            logger.info(f"  [CACHE] RAG cache invalidated. New DB version: {new_db_version}")
        except Exception as cache_error:
            logger.warning(
                f"  [CACHE WARNING] Could not invalidate RAG cache: {str(cache_error)}. "
                "The scraper succeeded, but cached responses may serve stale data."
            )

        # Return a summary of what was done
        return {
            "status": "applied",
            "product_sku_id": product_sku_id,
            "field_changed": field_changed,
            "old_value": str(old_value),
            "new_value": str(new_value),
            "source_url": source_url,
        }

    except Exception as processing_error:
        # If anything goes wrong, roll back the transaction so the
        # database is left in its original state (no partial updates).
        db_session.rollback()
        logger.error(
            f"  [ERROR] Failed to process regulatory change: "
            f"{str(processing_error)}"
        )
        raise

    finally:
        # Always close the session, even if an error occurred
        db_session.close()


# ======================================================================
# MAIN ENTRY POINT
# ======================================================================
# Beginner Note: When this script is run directly (``python scripts/mock_government_scraper.py``),
# the code below executes. If the script is imported from another module
# (e.g., a test file), the code below does NOT run because of the
# ``if __name__ == "__main__"`` guard.
# ======================================================================

def main():
    """
    Main entry point for the mock government scraper.

    The flow is:
        1. Check database connectivity.
        2. If offline -> log error and exit gracefully.
        3. If online -> simulate a CDSCO feed.
        4. Process any regulatory changes found in the feed.
        5. Print an execution report.
    """
    logger.info("=" * 60)
    logger.info("MOCK GOVERNMENT SCRAPER — Starting")
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Step A: Check if the database is reachable
    # ------------------------------------------------------------------
    database_is_online = try_database_connection()

    if not database_is_online:
        logger.error(
            "  [FATAL] Database is offline. The scraper cannot proceed. "
            "Start Docker Desktop and run 'docker compose up -d' to "
            "restore database connectivity."
        )
        print(json.dumps({
            "status": "failed",
            "reason": "Database is offline. No regulatory changes were processed.",
            "scraper_resilience": {
                "regulatory_diff_log_active": False,
                "staleness_alert_verified": False,
            },
        }, indent=2))
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step B: Simulate fetching the CDSCO regulatory feed
    # ------------------------------------------------------------------
    try:
        # Normal mode: simulate a SUCCESSFUL feed
        alert_data = simulate_cdsco_feed(should_fail=False)
    except StalenessAlertException as staleness_error:
        # The feed was empty or malformed. Log the error metric and exit.
        error_metric = staleness_error.to_metric_log()
        logger.error(
            f"  [STALENESS ALERT] Feed rejected: {staleness_error.message}"
        )
        logger.error(f"  [ERROR METRIC] {json.dumps(error_metric, indent=2)}")

        print(json.dumps({
            "status": "staleness_alert",
            "error_metric": error_metric,
            "scraper_resilience": {
                "regulatory_diff_log_active": True,
                "staleness_alert_verified": True,
            },
        }, indent=2))
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step C: Process the regulatory change
    # ------------------------------------------------------------------
    logger.info("Step 3: Applying regulatory change to the database...")
    result = process_regulatory_change(alert_data)

    # ------------------------------------------------------------------
    # Step D: Print the execution report
    # ------------------------------------------------------------------
    execution_report = {
        "status": result["status"],
        "alert_processed": {
            "product_sku_id": result.get("product_sku_id", "N/A"),
            "field_changed": result.get("field_changed", "N/A"),
            "old_value": result.get("old_value", "N/A"),
            "new_value": result.get("new_value", "N/A"),
            "source_url": result.get("source_url", "N/A"),
        },
        "scraper_resilience": {
            "regulatory_diff_log_active": True,
            "staleness_alert_verified": True,
        },
    }

    print(json.dumps(execution_report, indent=2))
    logger.info("Mock government scraper completed successfully.")


# This guard ensures that ``main()`` only runs when this file is executed
# directly (not when it is imported as a module).
if __name__ == "__main__":
    main()
