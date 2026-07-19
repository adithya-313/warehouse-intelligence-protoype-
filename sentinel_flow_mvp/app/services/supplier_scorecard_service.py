"""
[STORY: THE VENDOR TELEMETRY ENGINE]
We calculate Trust Score and SLA dynamically based on the delta
between Intent (Purchase Orders) and Reality (Actual Deliveries).
"""

from sqlalchemy.orm import Session
from app.infrastructure.models import SupplierModel, PurchaseOrderModel
from app.domain.schemas import DistributorScorecardResponse


def generate_financial_scorecard(db: Session, supplier_id: str) -> DistributorScorecardResponse:
    # 1. Fetch Supplier Data
    supplier = db.query(SupplierModel).filter(
        SupplierModel.supplier_id == supplier_id
    ).first()

    # Extract name from industry_specific_metadata (JSONB dict) if available
    supplier_name = "Unknown Vendor"
    if supplier and supplier.industry_specific_metadata:
        supplier_name = supplier.industry_specific_metadata.get(
            "name", f"Vendor {supplier_id}"
        )

    # 2. Fetch Purchase Orders (The State Machine)
    orders = db.query(PurchaseOrderModel).filter(
        PurchaseOrderModel.supplier_id == supplier_id
    ).all()

    if not orders:
        return DistributorScorecardResponse(
            supplier_id=supplier_id,
            name=supplier_name,
            financial_loss_rupees=0.0,
            delivery_success_rate=100,
            trust_score=100,
            risk_level="TRUSTED",
            recent_failures=0,
        )

    # 3. Telemetry Calculations
    total_orders = len(orders)
    on_time_deliveries = 0
    financial_loss = 0.0
    recent_failures = 0

    for po in orders:
        # Check SLA (Time Delta)
        is_late = False
        if po.actual_delivery_date and po.expected_delivery_date:
            if po.actual_delivery_date > po.expected_delivery_date:
                is_late = True

        # Check Fulfillment (Volume Delta)
        is_short = False
        ordered = po.ordered_qty or 0
        delivered = po.delivered_qty or 0
        if delivered < ordered:
            is_short = True
            # Financial Loss: (Missed quantity) * (Expected MRP - Cost Price)
            margin = (po.expected_mrp or 0) - (po.cost_price or 0)
            financial_loss += float((ordered - delivered) * margin)

        if is_late or is_short:
            recent_failures += 1
        else:
            on_time_deliveries += 1

    # 4. Aggregation & Scoring
    delivery_success_rate = int((on_time_deliveries / total_orders) * 100)

    # Trust Score Heuristic: Starts at 100, drops by 15 per failure, bottoms at 0
    trust_score = max(0, 100 - (recent_failures * 15))

    # Risk Level Gate
    risk_level = "TRUSTED"
    if trust_score < 70:
        risk_level = "WARNING"
    if trust_score < 40:
        risk_level = "HIGH"

    return DistributorScorecardResponse(
        supplier_id=supplier_id,
        name=supplier_name,
        financial_loss_rupees=round(financial_loss, 2),
        delivery_success_rate=delivery_success_rate,
        trust_score=trust_score,
        risk_level=risk_level,
        recent_failures=recent_failures,
    )
