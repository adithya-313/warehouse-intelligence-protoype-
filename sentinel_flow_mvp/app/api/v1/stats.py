from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from app.api.dependencies import get_current_tenant
from app.infrastructure.database import get_database_session
from app.infrastructure.models import TelemetryModel, SupplierModel
from app.infrastructure.db.models import LoRAAdapterRegistry

# Define the precise Pydantic response contract
class SystemStatsResponse(BaseModel):
    total_telemetry_records: int
    total_suppliers: int
    active_adapters: int
    total_adapters: int
    neural_backbone: str

router = APIRouter()

@router.get("/stats", response_model=SystemStatsResponse)
def get_system_stats(
    db: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant),
):
    """Aggregates high-level system telemetry for the Core Infrastructure dashboard."""
    
    # 1. ADMIN BYPASS: system_admin counts all records; otherwise scoped
    if tenant_id == "system_admin":
        total_records = db.query(func.count(TelemetryModel.recorded_at)).scalar() or 0
    else:
        total_records = db.query(func.count(TelemetryModel.recorded_at))\
                          .filter(TelemetryModel.tenant_id == tenant_id).scalar() or 0
    
    # 2. Count distinct suppliers
    total_suppliers = db.query(func.count(SupplierModel.supplier_id)).scalar() or 0
    
    # 3. Count LoRA Adapters
    total_adapters = db.query(func.count(LoRAAdapterRegistry.id)).scalar() or 0
    active_adapters = db.query(func.count(LoRAAdapterRegistry.id)).filter(
        LoRAAdapterRegistry.status == "ACTIVE"
    ).scalar() or 0

    return SystemStatsResponse(
        total_telemetry_records=total_records,
        total_suppliers=total_suppliers,
        active_adapters=active_adapters,
        total_adapters=total_adapters,
        neural_backbone="amazon/chronos-t5-mini" # The actual model used in the backend
    )
