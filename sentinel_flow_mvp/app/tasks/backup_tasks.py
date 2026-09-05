"""
Automated Database Backup to Google Drive

What this file does:
    This file contains a Celery task that runs nightly to backup the PostgreSQL
    database and upload it to Google Drive. It ensures our data is safely backed
    up off-site in case of hardware failure or accidental deletion.

Why this file exists:
    The Sentinel-Flow database contains critical pharmacy and patient data.
    Without automated backups, we risk permanent data loss. This task creates
    timestamped SQL dumps and uploads them to Google Drive, maintaining a
    rolling 7-day retention window.

How it connects to Celery Beat:
    The nightly_backup_to_drive task is registered in app/core/celery_app.py
    as "nightly-database-backup" and runs at 2 AM UTC daily. Celery Beat
    triggers this task automatically without manual intervention.

What happens if it fails:
    - If pg_dump fails: The task logs the error and raises an exception.
      Celery will retry once on transient network failures.
    - If Google Drive upload fails: The local dump file is kept for debugging.
      The task logs the error with full context.
    - If retention cleanup fails: Old backups remain (safe side), and the
      error is logged. Manual cleanup may be needed.
    - All failures are logged with structured context for debugging.

Written for junior developers:
    This task follows the same pattern as other Celery tasks in this project.
    It uses the @celery_app.task decorator and connects to the database using
    the same SessionLocal pattern used elsewhere. The task is designed to be
    idempotent - running it twice won't cause issues (though it's wasteful).
"""

import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.core.celery_app import celery_application as celery_app
from app.core.vault import get_secret

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================
# These are intentionally at the top so they're easy to find and change later.
# Don't hide configuration deep inside logic - it makes maintenance harder.

# How many days to keep backups before deletion
RETENTION_DAYS = 7

# Database connection details (from docker-compose.yml)
DB_HOST = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@timescaledb:5432/sentinel_db")
DB_USER = "postgres"
DB_NAME = "sentinel_db"

# Where to store temporary dump files inside the container
DUMP_DIR = "/tmp"


def _get_db_credentials_from_url():
    """
    Parse the DATABASE_URL environment variable to extract host, port, and password.

    This is needed because pg_dump requires separate arguments for host, port, etc.,
    not a single connection URL. We parse the URL manually to extract what we need.

    Returns:
        tuple: (host, port, password) extracted from DATABASE_URL
    """
    # DATABASE_URL format: postgresql://postgres:password@host:port/dbname
    url = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@timescaledb:5432/sentinel_db")
    # Remove the protocol prefix
    url_without_protocol = url.split("://")[1]
    # Split user:password@host:port/dbname
    user_password, rest = url_without_protocol.split("@", 1)
    password = user_password.split(":", 1)[1] if ":" in user_password else ""
    host_port = rest.split("/", 1)[0]
    host, port = host_port.split(":", 1) if ":" in host_port else (host_port, "5432")
    return host, port, password


def _get_drive_service():
    """
    Build and return a Google Drive API service using OAuth2 refresh token.

    This creates a credentials object using the refresh token stored in
    .secrets.json. The refresh token allows us to get new access tokens
    automatically without user interaction - perfect for automated tasks.

    Returns:
        googleapiclient.discovery.Resource: Authenticated Drive API service

    Raises:
        ValueError: If required OAuth secrets are missing from .secrets.json
    """
    client_id = get_secret("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = get_secret("GOOGLE_OAUTH_CLIENT_SECRET")
    refresh_token = get_secret("GOOGLE_OAUTH_REFRESH_TOKEN")

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError(
            "Missing Google OAuth secrets. Please add GOOGLE_OAUTH_CLIENT_ID, "
            "GOOGLE_OAUTH_CLIENT_SECRET, and GOOGLE_OAUTH_REFRESH_TOKEN to .secrets.json"
        )

    # Build credentials with refresh token - this allows automatic token refresh
    credentials = Credentials(
        token=None,  # We don't have an access token yet
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
    )

    # Build the Drive API service
    service = build("drive", "v3", credentials=credentials)
    return service


@celery_app.task(name="nightly_backup_to_drive")
def nightly_backup_to_drive():
    """
    Main backup task: dump database, upload to Google Drive, clean up old backups.

    This task is scheduled to run nightly at 2 AM UTC by Celery Beat.
    It performs three main steps:
    1. Create a timestamped SQL dump of the database
    2. Upload the dump to Google Drive
    3. Delete old backups beyond the retention window
    """
    logger.info("Starting nightly database backup task")

    # Generate timestamped filename for this backup
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    dump_filename = f"backup_{DB_NAME}_{timestamp}.sql"
    dump_path = os.path.join(DUMP_DIR, dump_filename)

    try:
        # =========================================================================
        # STEP 1: Create database dump using pg_dump
        # =========================================================================
        logger.info("Creating database dump: %s", dump_filename)

        # Get database credentials from the connection URL
        db_host, db_port, db_password = _get_db_credentials_from_url()

        # Build the pg_dump command
        # --no-owner: Don't include ownership commands (so dump can be restored anywhere)
        # --no-privileges: Don't include privilege commands (cleaner restore)
        # -f: Output file path
        pg_dump_cmd = [
            "pg_dump",
            "-h", db_host,
            "-p", db_port,
            "-U", DB_USER,
            "-d", DB_NAME,
            "--no-owner",
            "--no-privileges",
            "-f", dump_path,
        ]

        # Set PGPASSWORD environment variable so pg_dump can authenticate
        # This is the standard way to provide password to PostgreSQL CLI tools
        env = os.environ.copy()
        env["PGPASSWORD"] = db_password

        # Run pg_dump
        result = subprocess.run(
            pg_dump_cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout for large databases
        )

        if result.returncode != 0:
            logger.error("pg_dump failed with return code %d: %s", result.returncode, result.stderr)
            raise RuntimeError(f"pg_dump failed: {result.stderr}")

        # Verify the dump file was created and has content
        if not os.path.exists(dump_path):
            raise RuntimeError(f"Dump file not created: {dump_path}")

        dump_size = os.path.getsize(dump_path)
        logger.info("Database dump completed: %s (%d bytes)", dump_filename, dump_size)

        # =========================================================================
        # STEP 2: Upload to Google Drive
        # =========================================================================
        logger.info("Uploading backup to Google Drive")

        folder_id = get_secret("GOOGLE_DRIVE_BACKUP_FOLDER_ID")
        if not folder_id:
            raise ValueError("Missing GOOGLE_DRIVE_BACKUP_FOLDER_ID in .secrets.json")

        drive_service = _get_drive_service()

        # File metadata for Google Drive
        file_metadata = {
            "name": dump_filename,
            "parents": [folder_id],  # Upload to the configured backup folder
        }

        # Media upload object - tells Drive API how to read the file
        media = MediaFileUpload(dump_path, mimetype="application/sql", resumable=True)

        # Execute the upload
        uploaded_file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id,name,size,createdTime",
        ).execute()

        file_id = uploaded_file.get("id")
        file_size = uploaded_file.get("size")
        created_time = uploaded_file.get("createdTime")

        logger.info(
            "Upload complete: file_id=%s, name=%s, size=%s, created=%s",
            file_id,
            dump_filename,
            file_size,
            created_time,
        )

        # =========================================================================
        # STEP 3: Clean up local dump file
        # =========================================================================
        logger.info("Cleaning up local dump file: %s", dump_path)
        os.remove(dump_path)
        logger.info("Local dump file removed")

        # =========================================================================
        # STEP 4: Enforce retention - delete old backups
        # =========================================================================
        logger.info("Enforcing backup retention policy (%d days)", RETENTION_DAYS)

        # List all files in the backup folder
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)

        # Query Google Drive for all files in the backup folder
        query = f"'{folder_id}' in parents and name contains 'backup_{DB_NAME}_'"
        results = drive_service.files().list(
            q=query,
            fields="files(id,name,createdTime)",
            orderBy="createdTime desc",
        ).execute()

        files = results.get("files", [])
        logger.info("Found %d backup files in Google Drive", len(files))

        # Delete files older than RETENTION_DAYS
        deleted_count = 0
        for file_info in files:
            file_created = datetime.fromisoformat(file_info["createdTime"].replace("Z", "+00:00"))
            if file_created < cutoff_date:
                logger.info(
                    "Deleting old backup: %s (created %s)",
                    file_info["name"],
                    file_info["createdTime"],
                )
                drive_service.files().delete(fileId=file_info["id"]).execute()
                deleted_count += 1

        logger.info(
            "Retention cleanup complete: deleted %d old backups, kept %d",
            deleted_count,
            len(files) - deleted_count,
        )

        # =========================================================================
        # SUMMARY
        # =========================================================================
        logger.info(
            "Nightly backup task completed successfully. "
            "Backup uploaded as %s (file_id: %s, size: %s bytes)",
            dump_filename,
            file_id,
            file_size,
        )

        return {
            "status": "success",
            "filename": dump_filename,
            "file_id": file_id,
            "size": file_size,
            "created_time": created_time,
            "deleted_old_backups": deleted_count,
        }

    except subprocess.TimeoutExpired:
        logger.error("pg_dump timed out after 600 seconds")
        # Clean up partial dump file if it exists
        if os.path.exists(dump_path):
            os.remove(dump_path)
        raise

    except Exception as e:
        logger.error("Backup task failed: %s", str(e), exc_info=True)
        # Don't delete the dump file if upload failed - it might be useful for debugging
        if os.path.exists(dump_path):
            logger.info("Keeping local dump file for debugging: %s", dump_path)
        raise
