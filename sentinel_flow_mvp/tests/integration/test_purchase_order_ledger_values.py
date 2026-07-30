"""
Integration tests for Purchase Order Ledger calculation.

Verifies that the ledger correctly aggregates values based on order status,
distinguishing between ordered and delivered quantities to prevent inflated
financial figures for partially delivered orders.
"""

import pytest
from datetime import date
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.infrastructure.models import PurchaseOrderModel, Tenant
from app.api.purchase_order_router import router as purchase_order_router
from app.infrastructure.database import get_database_session

@pytest.fixture
def isolation_client(mock_db_session):
    """
    Creates a specific test client for the purchase order router.
    """
    app = FastAPI()
    app.include_router(purchase_order_router, prefix="/api/v1")
    app.dependency_overrides[get_database_session] = lambda: mock_db_session
    
    with TestClient(app) as c:
        yield c

class TestLedgerValueCalculation:
    """Tests to ensure the ledger calculates values accurately based on status."""

    @pytest.fixture
    def setup_orders(self, mock_db_session):
        # Create Tenant
        tenant = Tenant(
            tenant_id="TENANT-VAL",
            name="Value Pharmacy"
        )
        mock_db_session.add(tenant)

        # 1. Fully Delivered Order (Ordered 50, Delivered 50, Cost 10.0) -> Expected 500.0
        po_full = PurchaseOrderModel(
            po_id="PO-FULL-1",
            tenant_id="TENANT-VAL",
            supplier_id="SUPP-1",
            sku_id="SKU-FULL",
            ordered_qty=50,
            delivered_qty=50,
            cost_price=Decimal("10.00"),
            expected_mrp=Decimal("15.00"),
            order_date=date(2026, 1, 1),
            expected_delivery_date=date(2026, 1, 5),
            status="FULFILLED"
        )
        
        # 2. Partially Delivered Order (Ordered 100, Delivered 40, Cost 10.0) -> Expected 400.0
        po_partial = PurchaseOrderModel(
            po_id="PO-PART-1",
            tenant_id="TENANT-VAL",
            supplier_id="SUPP-1",
            sku_id="SKU-PART",
            ordered_qty=100,
            delivered_qty=40,
            cost_price=Decimal("10.00"),
            expected_mrp=Decimal("15.00"),
            order_date=date(2026, 1, 1),
            expected_delivery_date=date(2026, 1, 5),
            status="PARTIAL"
        )
        
        # 3. Pending Order (Ordered 200, Delivered 0, Cost 5.0) -> Expected 1000.0 (Committed)
        po_pending = PurchaseOrderModel(
            po_id="PO-PEND-1",
            tenant_id="TENANT-VAL",
            supplier_id="SUPP-1",
            sku_id="SKU-PEND",
            ordered_qty=200,
            delivered_qty=0,
            cost_price=Decimal("5.00"),
            expected_mrp=Decimal("15.00"),
            order_date=date(2026, 1, 1),
            expected_delivery_date=date(2026, 1, 5),
            status="PENDING"
        )
        
        # We need to simulate the db.query().filter().order_by().all()
        def mock_query_side_effect(*args, **kwargs):
            from unittest import mock
            mock_query = mock.MagicMock()
            mock_filter = mock.MagicMock()
            mock_order_by = mock.MagicMock()
            mock_order_by.all.return_value = [po_full, po_partial, po_pending]
            mock_filter.order_by.return_value = mock_order_by
            mock_query.filter.return_value = mock_filter
            return mock_query
            
        mock_db_session.query.side_effect = mock_query_side_effect
        
        return [po_full, po_partial, po_pending]

    def test_ledger_values_are_correct_for_all_statuses(self, isolation_client, setup_orders):
        """
        ACT & ASSERT: Call GET /purchase-orders and verify the calculated total_value_rupees.
        """
        response = isolation_client.get(
            "/api/v1/purchase-orders",
            headers={"X-Tenant-ID": "TENANT-VAL"}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Map by PO ID for easy assertion
        data_map = {item["po_id"]: item for item in data}
        
        assert data_map["PO-FULL-1"]["total_value_rupees"] == 500.0
        
        assert data_map["PO-PART-1"]["total_value_rupees"] == 400.0
        assert data_map["PO-PART-1"]["ordered_value_rupees"] == 1000.0
        assert data_map["PO-PART-1"]["delivered_value_rupees"] == 400.0
        
        assert data_map["PO-PEND-1"]["total_value_rupees"] == 1000.0
        assert data_map["PO-PEND-1"]["ordered_value_rupees"] == 1000.0
        assert data_map["PO-PEND-1"]["delivered_value_rupees"] == 0.0
