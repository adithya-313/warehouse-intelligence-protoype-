from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

from app.infrastructure.database import get_database_session
from app.infrastructure.models import NotificationModel
from app.api.dependencies import get_current_tenant
from app.health_risk.infrastructure.db_models import HealthRiskScoreModel

router = APIRouter(prefix="/notifications", tags=["Notifications"])

class NotificationResponse(BaseModel):
    id: int
    title: str
    message: str
    alert_type: str
    # Deep-link the notification to a health risk score (null for non-risk alerts).
    health_risk_score_id: Optional[int] = None
    # Disease the linked score belongs to. DERIVED at query time from the
    # health_risk_scores row (see get_notifications) rather than stored on
    # the notification — the score row is the single source of truth.
    disease_category: Optional[str] = None
    is_read: bool
    created_at: datetime

@router.get("", response_model=List[NotificationResponse])
@router.get("/", response_model=List[NotificationResponse])
def get_notifications(tenant_id: str = Depends(get_current_tenant), db: Session = Depends(get_database_session)):
    notifications = db.query(NotificationModel).filter(
        NotificationModel.tenant_id == tenant_id
    ).order_by(desc(NotificationModel.created_at)).limit(50).all()

    # Derive disease_category in one extra query instead of persisting a
    # duplicate column: the health_risk_scores row already knows its disease,
    # and linking through health_risk_score_id keeps a single source of truth.
    score_ids = [
        n.health_risk_score_id for n in notifications
        if n.health_risk_score_id is not None
    ]
    disease_by_score_id: dict = {}
    if score_ids:
        score_rows = db.query(HealthRiskScoreModel).filter(
            HealthRiskScoreModel.id.in_(score_ids)
        ).all()
        disease_by_score_id = {row.id: row.disease_category for row in score_rows}

    return [
        NotificationResponse(
            id=n.id,
            title=n.title,
            message=n.message,
            alert_type=n.alert_type,
            health_risk_score_id=n.health_risk_score_id,
            is_read=n.is_read,
            created_at=n.created_at,
            disease_category=disease_by_score_id.get(n.health_risk_score_id),
        )
        for n in notifications
    ]

@router.patch("/{notification_id}/read")
def mark_as_read(notification_id: int, tenant_id: str = Depends(get_current_tenant), db: Session = Depends(get_database_session)):
    notif = db.query(NotificationModel).filter(
        NotificationModel.id == notification_id, NotificationModel.tenant_id == tenant_id
    ).first()
    if notif:
        notif.is_read = True
        db.commit()
    return {"status": "success"}
