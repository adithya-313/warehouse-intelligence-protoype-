"""
Background Celery task that runs the full health-risk ingestion pipeline
for every pharmacy that has opted in.

This runs on a 6-hour schedule (defined in celery_app.py). It checks the
global HEALTH_RISK_ENABLED flag first, then processes each tenant where
health_risk_enabled is True and a pincode is configured.
"""

import logging

from app.core.celery_app import celery_application as celery_app
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import Tenant
from app.core.config import get_application_settings
from app.health_risk.service.ingestion_service import run_ingestion_for_pincode

logger = logging.getLogger(__name__)

# Load settings once at module level so the task does not re-read config
# on every cycle. If the app is restarted, the module is re-imported anyway.
settings = get_application_settings()


@celery_app.task(name="run_health_risk_ingestion_task")
def run_health_risk_ingestion_task():
    """
    Scheduled background job that runs health-risk scoring for all opted-in pharmacies.

    This is the replacement for the old synchronous call in procurement_router.py.
    The API endpoint now only READS pre-computed scores from the database instead
    of triggering ingestion inline during an HTTP request.
    """

    # ------------------------------------------------------------------
    # Step 1: Check the global kill switch.
    # If HEALTH_RISK_ENABLED is False, do nothing — the global flag
    # acts as an emergency stop for all pharmacies at once.
    # ------------------------------------------------------------------
    if not settings.HEALTH_RISK_ENABLED:
        logger.info("health risk ingestion skipped — globally disabled")
        return

    logger.info("Starting health risk ingestion cycle for all opted-in pharmacies.")

    # Open a fresh database session owned by this task.
    # We do NOT reuse a request-scoped session because this runs in a
    # background worker process, not inside an HTTP request.
    db = SessionLocal()
    try:

        # ------------------------------------------------------------------
        # Step 2: Find every tenant that has opted in AND has a pincode.
        # Both conditions must be true — without a pincode we cannot
        # fetch location-specific weather or trends data.
        # ------------------------------------------------------------------
        enabled_tenants = (
            db.query(Tenant)
            .filter(
                Tenant.health_risk_enabled == True,
                Tenant.pincode.isnot(None),
            )
            .all()
        )

        logger.info(
            "Found %d tenant(s) with health_risk enabled.",
            len(enabled_tenants),
        )

        # Keep counters for the final summary log line
        succeeded = 0
        failed = 0

        # ------------------------------------------------------------------
        # Step 3: Process each tenant one at a time.
        # Each tenant is protected by its OWN try/except block so that
        # a single failure (e.g. pytrends rate limit, network timeout)
        # does NOT crash the entire ingestion cycle or skip remaining
        # pharmacies.
        # ------------------------------------------------------------------
        for tenant in enabled_tenants:

            # Log which pharmacy we are about to process
            logger.info(
                "Processing health risk for tenant_id=%s, pincode=%s",
                tenant.tenant_id,
                tenant.pincode,
            )

            try:

                # Run the full scoring pipeline for this pharmacy's pincode.
                # This fetches Google Trends, reads weather data, calculates
                # the risk score via TransparentFormulaScorer, and saves the
                # result as a new HealthRiskScoreModel row.
                results = run_ingestion_for_pincode(
                    pincode=tenant.pincode,
                    db=db,
                    settings=settings,
                )

                # IMPORTANT: An empty list means every disease silently
                # failed inside run_ingestion_for_pincode's own per-disease
                # try/except, even though no exception reached us. Today,
                # that is incorrectly counted as a success. We fix that
                # here: treat zero results the SAME as a caught exception.
                if len(results) == 0:

                    # Soft failure — no exception was raised, but no
                    # disease was scored either. Count as failed and log
                    # a clear warning so operators can investigate.
                    failed += 1
                    logger.warning(
                        "Health risk ingestion produced zero scored diseases "
                        "for tenant_id=%s, pincode=%s — "
                        "treating as a failed cycle for this tenant.",
                        tenant.tenant_id,
                        tenant.pincode,
                    )

                else:

                    # Real success — at least one disease was scored.
                    succeeded += 1
                    logger.info(
                        "Successfully scored health risk "
                        "for tenant_id=%s, pincode=%s",
                        tenant.tenant_id,
                        tenant.pincode,
                    )

                    # Auto-onboarding gate: the first time real data
                    # arrives for a pharmacy, flip their feature flag so
                    # future cycles pick them up automatically. We check
                    # the flag is still False to avoid an unnecessary
                    # db.commit() when there is nothing to change.
                    if not tenant.health_risk_enabled:

                        tenant.health_risk_enabled = True
                        db.commit()
                        logger.info(
                            "Auto-enabled health_risk for tenant_id=%s "
                            "on first successful ingestion.",
                            tenant.tenant_id,
                        )

            except Exception as error:

                # One tenant's failure must NOT stop the rest.
                # Log the error clearly with the tenant_id so operators
                # can investigate, then move on to the next tenant.
                failed += 1
                logger.exception(
                    "Health risk ingestion FAILED for tenant_id=%s, pincode=%s: %s",
                    tenant.tenant_id,
                    tenant.pincode,
                    error,
                )

        # ------------------------------------------------------------------
        # Step 4: Log a clear summary so operators can monitor the job.
        # ------------------------------------------------------------------
        logger.info(
            "Health risk ingestion complete. "
            "Processed=%d, Succeeded=%d, Failed=%d",
            len(enabled_tenants),
            succeeded,
            failed,
        )

    except Exception as error:
        # Catch unexpected errors at the outer level (e.g. the DB query
        # for enabled_tenants itself failed). Log and re-raise so Celery
        # knows the task failed.
        logger.exception(
            "Fatal error in health risk ingestion cycle: %s",
            error,
        )
        raise

    finally:
        # Always close the session to free database connections
        db.close()
