"""Risk Dashboard API Routes.

Provides a live operational threat overlay for the supply chain,
surfacing stockout risks, dead stock, and anomaly alerts from
the telemetry database.
"""

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_tenant
from app.domain.schemas import RiskDashboardResponse
from app.infrastructure.database import get_database_session
from app.services.risk_service import get_risk_dashboard

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter()


@router.get(
    path="/dashboard",
    response_model=RiskDashboardResponse,
    summary="Live risk overlay for supply chain threats",
    description="Returns stockouts, dead stock, and anomaly alerts aggregated from telemetry.",
)
def get_risk_dashboard_endpoint(
    database_session: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant),
) -> RiskDashboardResponse:
    """Fetch the live operational threat overlay.

    Queries the latest 30 days of inventory telemetry, classifies
    each supplier into risk categories, and returns a strictly typed
    RiskDashboardResponse that the frontend renders directly.
    """
    raw_data = get_risk_dashboard(database_session, tenant_id=tenant_id)
    return RiskDashboardResponse(**raw_data)


from app.infrastructure.models import TelemetryModel

@router.get("/catalog")
def get_hardware_catalog(
    db: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant),
):
    """ADMIN BYPASS: system_admin sees all tenants. Otherwise, scoped to tenant_id."""
    query = db.query(TelemetryModel.supplier_id, TelemetryModel.sku_id).distinct()
    if tenant_id != "system_admin":
        query = query.filter(TelemetryModel.tenant_id == tenant_id)
    results = query.all()

    catalog = {}
    for supplier, sku in results:
        if supplier not in catalog:
            catalog[supplier] = []
        if sku and sku not in catalog[supplier]:
            catalog[supplier].append(sku)

    return [{"supplier_id": k, "skus": v} for k, v in catalog.items()]
