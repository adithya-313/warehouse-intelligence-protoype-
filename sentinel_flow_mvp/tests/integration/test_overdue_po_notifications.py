import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from app.infrastructure.models import PurchaseOrderModel, NotificationModel, SupplierModel, MedicationModel, Tenant
from app.tasks.purchase_order_tasks import check_overdue_purchase_orders
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.infrastructure.models import Base

@compiles(JSONB, 'sqlite')
def compile_jsonb_sqlite(type_, compiler, **kw):
    return 'JSON'

@compiles(ARRAY, 'sqlite')
def compile_array_sqlite(type_, compiler, **kw):
    return 'JSON'

@pytest.fixture
def sqlite_db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    yield session
    session.close()

@pytest.fixture
def setup_overdue_po_data(sqlite_db_session: Session):
    db = sqlite_db_session
    # Setup Tenant A
    tenant_a = Tenant(tenant_id="tenant-overdue-A", name="Tenant A")
    db.merge(tenant_a)
    
    # Setup Tenant B (for isolation)
    tenant_b = Tenant(tenant_id="tenant-overdue-B", name="Tenant B")
    db.merge(tenant_b)

    # Setup Supplier and Medication
    supplier = SupplierModel(supplier_id="SUPP-OVERDUE-1", system_origin="TALLY", industry_vertical="PHARMA")
    db.merge(supplier)
    
    from sqlalchemy import text
    sqlite_db_session.execute(text(
        "INSERT INTO medications (sku_id, apis, therapeutic_classes, cdsco_schedule, is_approved_by_curator) "
        "VALUES ('SKU-OVERDUE-1', '[]', '[]', 'OTC', 1)"
    ))
    
    db.commit()
    
    # Cleanup any existing notifications from previous tests
    db.query(NotificationModel).filter(NotificationModel.alert_type == "OVERDUE_ORDER").delete()
    db.commit()

    return tenant_a.tenant_id, tenant_b.tenant_id, supplier.supplier_id, "SKU-OVERDUE-1"

def create_po(db: Session, tenant_id, po_id, supplier_id, sku_id, expected_delivery_date, status="SUBMITTED"):
    po = PurchaseOrderModel(
        po_id=po_id,
        tenant_id=tenant_id,
        supplier_id=supplier_id,
        sku_id=sku_id,
        ordered_qty=10,
        cost_price=10.0,
        expected_mrp=15.0,
        order_date=expected_delivery_date - timedelta(days=2),
        expected_delivery_date=expected_delivery_date,
        status=status
    )
    db.merge(po)
    db.commit()
    return po

from unittest.mock import patch

def test_escalation_and_duplicate_prevention(sqlite_db_session: Session, setup_overdue_po_data):
    db = sqlite_db_session
    tenant_a, tenant_b, supp_id, sku_id = setup_overdue_po_data
    today = datetime.now(timezone.utc).date()
    po_id = "PO-OVD-123"

    with patch("app.tasks.purchase_order_tasks.SessionLocal", return_value=sqlite_db_session):
        # Step 1: PO is 1 day overdue (Tier 1)
        create_po(db, tenant_a, po_id, supp_id, sku_id, today - timedelta(days=1))
        
        check_overdue_purchase_orders()
        
        notifications = db.query(NotificationModel).filter_by(reference_id=po_id).all()
        assert len(notifications) == 1
        assert "1 days past" in notifications[0].message
        assert notifications[0].tenant_id == tenant_a
        
        # Step 2: Run job again on the same day (delay still 1 day)
        check_overdue_purchase_orders()
        
        notifications = db.query(NotificationModel).filter_by(reference_id=po_id).all()
        assert len(notifications) == 1 # Duplicate prevention worked!
        
        # Step 3: PO is 3 days overdue (Tier 2)
        po = db.query(PurchaseOrderModel).filter_by(po_id=po_id).first()
        po.expected_delivery_date = today - timedelta(days=3)
        db.commit()
        
        check_overdue_purchase_orders()
        
        notifications = db.query(NotificationModel).filter_by(reference_id=po_id).order_by(NotificationModel.id).all()
        assert len(notifications) == 2 # Second notification created
        assert "3 days past" in notifications[1].message
        
        # Step 4: PO is 7 days overdue (Tier 3)
        po = db.query(PurchaseOrderModel).filter_by(po_id=po_id).first()
        po.expected_delivery_date = today - timedelta(days=7)
        db.commit()
        
        check_overdue_purchase_orders()
        
        notifications = db.query(NotificationModel).filter_by(reference_id=po_id).order_by(NotificationModel.id).all()
        assert len(notifications) == 3 # Third notification created
        assert "7 days past" in notifications[2].message
        
        # Step 5: PO is 10 days overdue (Still Tier 3)
        po = db.query(PurchaseOrderModel).filter_by(po_id=po_id).first()
        po.expected_delivery_date = today - timedelta(days=10)
        db.commit()
        
        check_overdue_purchase_orders()
        
        notifications = db.query(NotificationModel).filter_by(reference_id=po_id).order_by(NotificationModel.id).all()
        assert len(notifications) == 3 # Max 3 notifications per PO!

def test_tenant_isolation(sqlite_db_session: Session, setup_overdue_po_data):
    db = sqlite_db_session
    tenant_a, tenant_b, supp_id, sku_id = setup_overdue_po_data
    today = datetime.now(timezone.utc).date()
    po_id_b = "PO-OVD-B-456"

    with patch("app.tasks.purchase_order_tasks.SessionLocal", return_value=sqlite_db_session):
        # Tenant B has a 2 days overdue PO
        create_po(db, tenant_b, po_id_b, supp_id, sku_id, today - timedelta(days=2))
        
        check_overdue_purchase_orders()
        
        # Ensure Tenant A has no notifications
        notifs_a = db.query(NotificationModel).filter_by(tenant_id=tenant_a).all()
        assert len(notifs_a) == 0
        
        # Ensure Tenant B got their notification
        notifs_b = db.query(NotificationModel).filter_by(tenant_id=tenant_b).all()
        assert len(notifs_b) == 1
        assert notifs_b[0].reference_id == po_id_b
