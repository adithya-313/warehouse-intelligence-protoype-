from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from datetime import datetime
from typing import List

from app.infrastructure.database import get_database_session
from app.infrastructure.models import NotificationModel
from app.api.dependencies import get_current_tenant

router = APIRouter(prefix="/notifications", tags=["Notifications"])

class NotificationResponse(BaseModel):
    id: int
    title: str
    message: str
    alert_type: str
    is_read: bool
    created_at: datetime

@router.get("/", response_model=List[NotificationResponse])
def get_notifications(tenant_id: str = Depends(get_current_tenant), db: Session = Depends(get_database_session)):
    return db.query(NotificationModel).filter(
        NotificationModel.tenant_id == tenant_id
    ).order_by(desc(NotificationModel.created_at)).limit(50).all()

@router.patch("/{notification_id}/read")
def mark_as_read(notification_id: int, tenant_id: str = Depends(get_current_tenant), db: Session = Depends(get_database_session)):
    notif = db.query(NotificationModel).filter(
        NotificationModel.id == notification_id, NotificationModel.tenant_id == tenant_id
    ).first()
    if notif:
        notif.is_read = True
        db.commit()
    return {"status": "success"}
