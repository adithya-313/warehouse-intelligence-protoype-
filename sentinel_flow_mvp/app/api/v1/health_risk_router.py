"""
Read-only API endpoints for the health-risk module.

WHY THIS ROUTER EXISTS:
The procurement_router.py health-risk branch lives inside the legacy
/procurement/disease-wave-alerts endpoint and mixes risk data with
alert generation logic. This file provides a clean, dedicated endpoint
that returns the CURRENT risk scores for a pharmacy without any alert
or notification side-effects — a simple "what is my risk right now?" query.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_tenant
from app.health_risk.api.schemas import (
    HealthRiskCurrentResponse,
    HealthRiskExplainResponse,
    HealthRiskHistoryResponse,
    HealthRiskScoreResponse,
)
from app.health_risk.infrastructure.db_models import HealthRiskScoreModel
from app.infrastructure.database import get_database_session
from app.infrastructure.models import Tenant

logger = logging.getLogger(__name__)

# No prefix here — prefix is applied in main.py when include_router is called.
router: APIRouter = APIRouter()


@router.get(
    path="/current",
    response_model=HealthRiskCurrentResponse,
    summary="Current health risk snapshot for the pharmacy's location",
)
def get_current_health_risk(
    database_session: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant),
) -> HealthRiskCurrentResponse:
    """Return the most recent health-risk score per disease for this pharmacy.

    Flow:
      1. Look up the Tenant row to find this pharmacy's registered pincode.
      2. Query HealthRiskScoreModel for that pincode, newest first.
      3. Deduplicate to keep only the latest row per disease category.
      4. Return a HealthRiskCurrentResponse with pincode and scores list.

    If the tenant has no pincode configured, we return 404 — the pharmacy
    admin needs to set one before location-based scoring can work.

    If the Celery background job has not run yet (cold start), we return
    a 200 with an empty scores list — this is a temporary state that
    resolves automatically once the first ingestion cycle completes.
    """
    # ------------------------------------------------------------------
    # Step 1: Look up the Tenant to get the pharmacy's registered pincode.
    # ------------------------------------------------------------------
    tenant = database_session.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()

    if tenant is None:
        # Tenant row missing — cannot determine which pincode to query.
        raise HTTPException(status_code=404, detail="Tenant not found.")

    if not tenant.pincode:
        # No pincode configured means location-based scoring cannot work.
        # The tenant admin must set a pincode in the tenants table first.
        raise HTTPException(
            status_code=404,
            detail="No pincode registered for this pharmacy yet. "
            "Set tenant.pincode in the tenants table before querying health risk scores.",
        )

    # ------------------------------------------------------------------
    # Step 2: Fetch all health risk scores for this pincode, newest first.
    # The background Celery job writes these rows every 6 hours.
    # ------------------------------------------------------------------
    all_score_rows = (
        database_session.query(HealthRiskScoreModel)
        .filter(HealthRiskScoreModel.pincode == tenant.pincode)
        .order_by(HealthRiskScoreModel.computed_at.desc())
        .all()
    )

    # ------------------------------------------------------------------
    # Step 3: Keep only the most recent row per disease category.
    # This is the same dedup pattern used in procurement_router.py:
    # because the query is ordered by computed_at DESC, the first time
    # we encounter a disease_category it IS the latest score for that
    # disease.
    # ------------------------------------------------------------------
    seen_diseases: set = set()
    latest_scores: list = []

    for row in all_score_rows:
        if row.disease_category not in seen_diseases:
            seen_diseases.add(row.disease_category)
            latest_scores.append(row)

    # ------------------------------------------------------------------
    # Step 4: Build and return the response.
    # If latest_scores is empty (cold start), we return an empty list
    # with a 200 status — this is the same behaviour as the
    # procurement_router health-risk branch.
    # ------------------------------------------------------------------
    return HealthRiskCurrentResponse(
        pincode=tenant.pincode,
        scores=[
            HealthRiskScoreResponse(
                disease_category=row.disease_category,
                score=row.score,
                confidence=row.confidence,
                computed_at=row.computed_at,
            )
            for row in latest_scores
        ],
    )


# =========================================================================
# GET /history — Full time-series of risk scores for a pharmacy
# =========================================================================

@router.get(
    path="/history",
    response_model=HealthRiskHistoryResponse,
    summary="Time-series of health risk scores for the pharmacy's location",
)
def get_health_risk_history(
    database_session: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant),
    days: int = Query(default=30, description="Number of days of history to return (max 365)."),
) -> HealthRiskHistoryResponse:
    """Return the full time-series of risk scores for this pharmacy.

    Unlike /current (which returns only the LATEST score per disease),
    /history returns ALL rows in the date range, ordered oldest first.
    This is designed for time-series charts that show how risk evolved
    over the past N days — you need every data point, not just the latest
    snapshot.

    Flow:
      1. Validate the days parameter (must be 1-365).
      2. Look up the Tenant row to find this pharmacy's registered pincode.
      3. Query HealthRiskScoreModel for that pincode within the date window.
      4. Return ALL matching rows in ascending chronological order (oldest
         first), with NO deduplication — the whole point is seeing change
         over time.
    """
    # ------------------------------------------------------------------
    # Step 1: Validate days parameter.
    # Prevent someone from querying an absurd range like 10 000 days
    # and pulling gigabytes of data, or passing 0 / negative values
    # that would break the timedelta math or return no rows.
    # This matches the same pattern used in supplier_router.py for limit.
    # ------------------------------------------------------------------
    if days <= 0 or days > 365:
        raise HTTPException(
            status_code=400,
            detail="days must be between 1 and 365.",
        )

    # ------------------------------------------------------------------
    # Step 2: Look up the Tenant to get the pharmacy's registered pincode.
    # Same logic as /current — we need the pincode to filter scores.
    # ------------------------------------------------------------------
    tenant = database_session.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()

    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    if not tenant.pincode:
        raise HTTPException(
            status_code=404,
            detail="No pincode registered for this pharmacy yet. "
            "Set tenant.pincode in the tenants table before querying health risk scores.",
        )

    # ------------------------------------------------------------------
    # Step 3: Calculate the cutoff date and query scores.
    # We ask for ALL rows that fall within the requested window —
    # multiple rows per disease category, across all categories.
    # ------------------------------------------------------------------
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

    score_rows = (
        database_session.query(HealthRiskScoreModel)
        .filter(HealthRiskScoreModel.pincode == tenant.pincode)
        .filter(HealthRiskScoreModel.computed_at >= cutoff_date)
        .order_by(HealthRiskScoreModel.computed_at.asc())
        .all()
    )

    # ------------------------------------------------------------------
    # Step 4: Build and return the response.
    # If score_rows is empty (cold start, or no data in the date range),
    # we return an empty list with a 200 status — same philosophy as
    # /current. The frontend can show "no data yet" gracefully.
    #
    # IMPORTANT DIFFERENCE FROM /current:
    # We do NOT deduplicate by disease_category here. The /history
    # endpoint is for time-series charts — it needs every data point so
    # the graph can show score changes over time. Deduplication would
    # hide those changes and defeat the purpose.
    # ------------------------------------------------------------------
    return HealthRiskHistoryResponse(
        pincode=tenant.pincode,
        days=days,
        scores=[
            HealthRiskScoreResponse(
                disease_category=row.disease_category,
                score=row.score,
                confidence=row.confidence,
                computed_at=row.computed_at,
            )
            for row in score_rows
        ],
    )


# =========================================================================
# GET /explain/{score_id} — Signal breakdown for one specific risk score
# =========================================================================

@router.get(
    path="/explain/{score_id}",
    response_model=HealthRiskExplainResponse,
    summary="Full signal breakdown behind one risk score entry",
)
def get_health_risk_explain(
    score_id: int,
    database_session: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant),
) -> HealthRiskExplainResponse:
    """Return the complete signal breakdown for one specific risk score.

    Unlike /current and /history (which return lists of scores), this
    endpoint returns the FULL detail of a SINGLE score row — including
    the contributing_factors dict that shows which raw inputs (trend
    data, weather data) produced this number.

    This lets a pharmacist click on any score in the UI and see the
    reasoning behind it, not just trust a bare number.

    Flow:
      1. Look up the Tenant to find the pharmacy's registered pincode.
      2. Query HealthRiskScoreModel by the given id.
      3. Verify ownership: the score's pincode MUST match the calling
         tenant's pincode (see SECURITY NOTE below).
      4. Return all fields including contributing_factors.

    SECURITY NOTE — CROSS-TENANT PROTECTION:
    The health_risk_scores table has NO tenant_id column — only pincode.
    A tenant's identity is only linked to a pincode via the Tenant table.
    If we fetched a row by id WITHOUT checking that its pincode matches
    the calling tenant's pincode, Tenant A could read Tenant B's health
    data just by guessing id numbers in the URL.

    The ownership check below prevents this: if the score row's pincode
    doesn't match the calling tenant's pincode, we return the EXACT SAME
    404 message as "row doesn't exist." This is deliberate — returning
    a different status (like 403) or a different message would tell an
    attacker "this id exists but belongs to someone else," which itself
    leaks information. From the caller's perspective, "doesn't exist"
    and "isn't yours" must look identical.
    """
    # ------------------------------------------------------------------
    # Step 1: Look up the Tenant to get the pharmacy's registered pincode.
    # Same logic as /current and /history.
    # ------------------------------------------------------------------
    tenant = database_session.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()

    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found.")

    if not tenant.pincode:
        raise HTTPException(
            status_code=404,
            detail="No pincode registered for this pharmacy yet. "
            "Set tenant.pincode in the tenants table before querying health risk scores.",
        )

    # ------------------------------------------------------------------
    # Step 2: Query the specific score row by id.
    # ------------------------------------------------------------------
    score_row = (
        database_session.query(HealthRiskScoreModel)
        .filter(HealthRiskScoreModel.id == score_id)
        .first()
    )

    # ------------------------------------------------------------------
    # Step 3: If no row with that id exists, return 404.
    # ------------------------------------------------------------------
    if score_row is None:
        raise HTTPException(
            status_code=404,
            detail="Health risk score not found.",
        )

    # ------------------------------------------------------------------
    # Step 4 — CRITICAL OWNERSHIP CHECK:
    # Verify that this score row's pincode matches the calling tenant's
    # pincode. If they don't match, the score belongs to a different
    # pharmacy — we must NOT return it.
    #
    # We use the EXACT SAME 404 message as Step 3 ("not found") so that
    # an attacker cannot distinguish "this id doesn't exist" from "this
    # id exists but isn't yours." Both cases look identical to the
    # caller, preventing information leakage.
    # ------------------------------------------------------------------
    if score_row.pincode != tenant.pincode:
        raise HTTPException(
            status_code=404,
            detail="Health risk score not found.",
        )

    # ------------------------------------------------------------------
    # Step 5: Return the full breakdown.
    # contributing_factors is already a dict from the JSON column — we
    # pass it through as-is, no transformation needed.
    # ------------------------------------------------------------------
    return HealthRiskExplainResponse(
        id=score_row.id,
        pincode=score_row.pincode,
        disease_category=score_row.disease_category,
        score=score_row.score,
        confidence=score_row.confidence,
        computed_at=score_row.computed_at,
        contributing_factors=score_row.contributing_factors,
    )
