import logging
from datetime import datetime, timezone
from sqlalchemy import func

from app.core.celery_app import celery_application as celery_app
from app.infrastructure.database import SessionLocal
from app.infrastructure.models import PurchaseOrderModel, NotificationModel, SupplierModel, MedicationModel

logger = logging.getLogger(__name__)

@celery_app.task(name="check_overdue_purchase_orders")
def check_overdue_purchase_orders():
    """
    Runs daily to find overdue purchase orders and generate notifications based on escalation tiers.
    Tiers: 1-2 days (Tier 1), 3-6 days (Tier 2), 7+ days (Tier 3).
    Max 3 notifications per PO.
    """
    logger.info("Starting check_overdue_purchase_orders task")
    db = SessionLocal()
    try:
        today = datetime.now(timezone.utc).date()
        
        # Query orders that are not fulfilled/failed and have passed their expected delivery date
        overdue_orders = db.query(
            PurchaseOrderModel, 
            SupplierModel.system_origin,  # We just need some supplier info, or better yet, join to get names
            MedicationModel.sku_id
        ).join(
            SupplierModel, PurchaseOrderModel.supplier_id == SupplierModel.supplier_id
        ).join(
            MedicationModel, PurchaseOrderModel.sku_id == MedicationModel.sku_id
        ).filter(
            PurchaseOrderModel.status.in_(["SUBMITTED", "PARTIAL"]),
            PurchaseOrderModel.expected_delivery_date < today
        ).all()
        
        logger.info(f"Found {len(overdue_orders)} overdue purchase orders")

        for po, supplier_origin, sku in overdue_orders:
            days_late = (today - po.expected_delivery_date).days
            
            if days_late < 1:
                continue

            # Determine Tier
            target_tier = 0
            if days_late >= 7:
                target_tier = 3
            elif days_late >= 3:
                target_tier = 2
            elif days_late >= 1:
                target_tier = 1

            # Count existing notifications for this PO
            existing_notifications_count = db.query(NotificationModel).filter(
                NotificationModel.tenant_id == po.tenant_id,
                NotificationModel.alert_type == "OVERDUE_ORDER",
                NotificationModel.reference_id == po.po_id
            ).count()

            # If we already sent the notification for this tier (or higher), skip
            if existing_notifications_count >= target_tier:
                continue

            # We need to send a new notification
            title = f"Overdue Order: {po.po_id}"
            message = (
                f"Your order for {po.ordered_qty}x {po.sku_id} from {po.supplier_id} "
                f"is {days_late} days past its expected delivery date."
            )

            new_notif = NotificationModel(
                tenant_id=po.tenant_id,
                title=title,
                message=message,
                alert_type="OVERDUE_ORDER",
                reference_id=po.po_id
            )
            db.add(new_notif)
            logger.info(f"Generated Tier {existing_notifications_count + 1} OVERDUE_ORDER notification for PO {po.po_id}")

        db.commit()
    except Exception as e:
        logger.error(f"Error in check_overdue_purchase_orders: {e}")
        db.rollback()
        raise
    finally:
        db.close()
    
    logger.info("Finished check_overdue_purchase_orders task")
