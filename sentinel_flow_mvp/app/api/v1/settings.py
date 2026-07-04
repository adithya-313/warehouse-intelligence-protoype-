from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.infrastructure.database import get_database_session
from app.api.dependencies import get_current_tenant
from app.domain.schemas import TenantSettingsUpdate, TenantSettingsResponse
from app.infrastructure.models import Tenant

router = APIRouter()

@router.get("/", response_model=TenantSettingsResponse)
def get_tenant_settings(
    db: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant)
):
    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    return TenantSettingsResponse(
        tenant_id=tenant.tenant_id,
        name=tenant.name,
        upi_id=tenant.upi_id,
        meta_whatsapp_token_configured=bool(tenant.meta_whatsapp_token),
        whatsapp_phone_id=tenant.whatsapp_phone_id
    )

@router.put("/", response_model=TenantSettingsResponse)
def update_tenant_settings(
    payload: TenantSettingsUpdate,
    db: Session = Depends(get_database_session),
    tenant_id: str = Depends(get_current_tenant)
):
    tenant = db.query(Tenant).filter(Tenant.tenant_id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
        
    if payload.upi_id is not None:
        tenant.upi_id = payload.upi_id
    if payload.meta_whatsapp_token is not None:
        tenant.meta_whatsapp_token = payload.meta_whatsapp_token
    if payload.whatsapp_phone_id is not None:
        tenant.whatsapp_phone_id = payload.whatsapp_phone_id
        
    db.commit()
    db.refresh(tenant)
    
    return TenantSettingsResponse(
        tenant_id=tenant.tenant_id,
        name=tenant.name,
        upi_id=tenant.upi_id,
        meta_whatsapp_token_configured=bool(tenant.meta_whatsapp_token),
        whatsapp_phone_id=tenant.whatsapp_phone_id
    )
