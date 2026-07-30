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

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_tenant
from app.health_risk.api.schemas import HealthRiskCurrentResponse, HealthRiskScoreResponse
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
