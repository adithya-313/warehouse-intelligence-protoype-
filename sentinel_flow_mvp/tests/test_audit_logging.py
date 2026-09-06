"""
Tests for audit logging in purchase order endpoints.

Verifies that:
1. create_bulk_purchase_order writes an audit row with action_type="CREATE"
2. receive_bulk_purchase_order writes an audit row with action_type="UPDATE"
3. The audit row captures correct tenant_id, entity_type, old_value, new_value
4. The audit row shares the same transaction as the business change (no separate commit)
"""

import uuid
from datetime import datetime, date
from unittest.mock import MagicMock, patch, call


class TestAuditLoggingOnReceive:
    """Test that receive_bulk_purchase_order writes correct audit entries."""

    @patch("app.api.purchase_order_router.log_audit_event")
    def test_receive_writes_audit_with_old_and_new_values(
        self,
        mock_log_audit,
        mock_db_session,
    ):
        """
        ARRANGE: Set up mock PO items with known status/quantities.
        ACT: Call receive_bulk_purchase_order with a delivery.
        ASSERT: log_audit_event was called with correct old_value, new_value,
                tenant_id, entity_type="purchase_order", action_type="UPDATE".
        """
        # --- ARRANGE: Mock PO items in SUBMITTED state with 0 delivered ---
        mock_po_1 = MagicMock()
        mock_po_1.po_id = "PO-TEST001"
        mock_po_1.sku_id = "SKU-001"
        mock_po_1.tenant_id = "test-tenant-001"
        mock_po_1.status = "SUBMITTED"
        mock_po_1.delivered_qty = 0
        mock_po_1.ordered_qty = 100

        mock_po_2 = MagicMock()
        mock_po_2.po_id = "PO-TEST001"
        mock_po_2.sku_id = "SKU-002"
        mock_po_2.tenant_id = "test-tenant-001"
        mock_po_2.status = "SUBMITTED"
        mock_po_2.delivered_qty = 0
        mock_po_2.ordered_qty = 50

        # Mock the query chain: db.query(...).filter(...).all() returns our POs
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.all.return_value = [mock_po_1, mock_po_2]
        mock_query.filter.return_value = mock_filter
        mock_db_session.query.return_value = mock_query

        # --- ACT: Call the receive endpoint ---
        from app.api.purchase_order_router import receive_bulk_purchase_order
        from app.domain.schemas import PurchaseOrderReceiveBulk, POItemReceive

        payload = PurchaseOrderReceiveBulk(
            po_id="PO-TEST001",
            actual_delivery_date=date(2026, 9, 5),
            items=[
                POItemReceive(sku_id="SKU-001", delivered_qty=80),
                POItemReceive(sku_id="SKU-002", delivered_qty=50),
            ],
        )

        result = receive_bulk_purchase_order(payload=payload, db=mock_db_session)

        # --- ASSERT: log_audit_event was called once ---
        assert mock_log_audit.call_count == 1

        # Extract the call arguments
        call_kwargs = mock_log_audit.call_args[1]

        # Verify core fields
        assert call_kwargs["tenant_id"] == "test-tenant-001"
        assert call_kwargs["entity_type"] == "purchase_order"
        assert call_kwargs["entity_id"] == "PO-TEST001"
        assert call_kwargs["action_type"] == "UPDATE"

        # Verify old_value captured the state BEFORE changes
        old_value = call_kwargs["old_value"]
        assert old_value is not None
        assert "items" in old_value
        assert len(old_value["items"]) == 2
        assert old_value["items"][0]["sku_id"] == "SKU-001"
        assert old_value["items"][0]["delivered_qty"] == 0
        assert old_value["items"][0]["status"] == "SUBMITTED"
        assert old_value["items"][1]["sku_id"] == "SKU-002"
        assert old_value["items"][1]["delivered_qty"] == 0

        # Verify new_value captured the state AFTER changes
        new_value = call_kwargs["new_value"]
        assert new_value is not None
        assert "items" in new_value
        assert len(new_value["items"]) == 2
        assert new_value["items"][0]["sku_id"] == "SKU-001"
        assert new_value["items"][0]["delivered_qty"] == 80
        assert new_value["items"][0]["status"] == "PARTIAL"  # 80 < 100
        assert new_value["items"][1]["sku_id"] == "SKU-002"
        assert new_value["items"][1]["delivered_qty"] == 50
        assert new_value["items"][1]["status"] == "FULFILLED"  # 50 == 50

    @patch("app.api.purchase_order_router.log_audit_event")
    def test_receive_does_not_commit_separately_for_audit(
        self,
        mock_log_audit,
        mock_db_session,
    ):
        """
        ARRANGE: Set up mock PO items.
        ACT: Call receive_bulk_purchase_order.
        ASSERT: log_audit_event was called but db.commit() was still called
                only once (by the endpoint itself, not by the audit helper).
        """
        mock_po = MagicMock()
        mock_po.po_id = "PO-TEST002"
        mock_po.sku_id = "SKU-003"
        mock_po.tenant_id = "test-tenant-002"
        mock_po.status = "SUBMITTED"
        mock_po.delivered_qty = 0
        mock_po.ordered_qty = 100

        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.all.return_value = [mock_po]
        mock_query.filter.return_value = mock_filter
        mock_db_session.query.return_value = mock_query

        from app.api.purchase_order_router import receive_bulk_purchase_order
        from app.domain.schemas import PurchaseOrderReceiveBulk, POItemReceive

        payload = PurchaseOrderReceiveBulk(
            po_id="PO-TEST002",
            actual_delivery_date=date(2026, 9, 5),
            items=[
                POItemReceive(sku_id="SKU-003", delivered_qty=100),
            ],
        )

        receive_bulk_purchase_order(payload=payload, db=mock_db_session)

        # The audit helper should NOT call commit itself
        mock_log_audit.assert_called_once()
        # The endpoint's own commit should have been called exactly once
        assert mock_db_session.commit.call_count == 1


class TestAuditLoggingOnCreate:
    """Test that create_bulk_purchase_order writes correct audit entries."""

    @patch("app.api.purchase_order_router.log_audit_event")
    def test_create_writes_audit_with_new_value(
        self,
        mock_log_audit,
        mock_db_session,
    ):
        """
        ARRANGE: Mock tenant lookup to return a valid tenant.
        ACT: Call create_bulk_purchase_order.
        ASSERT: log_audit_event was called with action_type="CREATE",
                old_value=None, new_value containing the PO details.
        """
        # --- ARRANGE: Mock tenant ---
        mock_tenant = MagicMock()
        mock_tenant.tenant_id = "test-tenant-003"

        # db.query(Tenant).first() should return our mock tenant
        mock_query = MagicMock()
        mock_query.first.return_value = mock_tenant
        mock_db_session.query.return_value = mock_query

        # --- ACT: Call the create endpoint ---
        from app.api.purchase_order_router import create_bulk_purchase_order
        from app.domain.schemas import PurchaseOrderBulkCreate, POLineItemCreate

        payload = PurchaseOrderBulkCreate(
            supplier_id="SUPP-001",
            expected_delivery_date=date(2026, 9, 10),
            items=[
                POLineItemCreate(sku_id="SKU-001", ordered_qty=100, cost_price=10.0, expected_mrp=15.0),
            ],
        )

        result = create_bulk_purchase_order(payload=payload, db=mock_db_session)

        # --- ASSERT: log_audit_event was called once ---
        assert mock_log_audit.call_count == 1

        call_kwargs = mock_log_audit.call_args[1]

        # Verify core fields
        assert call_kwargs["tenant_id"] == "test-tenant-003"
        assert call_kwargs["entity_type"] == "purchase_order"
        assert call_kwargs["action_type"] == "CREATE"
        assert call_kwargs["old_value"] is None  # No previous state for CREATE

        # Verify new_value contains the PO details
        new_value = call_kwargs["new_value"]
        assert new_value is not None
        assert "po_id" in new_value
        assert new_value["supplier_id"] == "SUPP-001"
        assert new_value["status"] == "SUBMITTED"
        assert len(new_value["items"]) == 1
        assert new_value["items"][0]["sku_id"] == "SKU-001"
        assert new_value["items"][0]["ordered_qty"] == 100
