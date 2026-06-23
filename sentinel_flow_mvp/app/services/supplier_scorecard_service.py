from sqlalchemy.orm import Session
from app.infrastructure.models import PurchaseOrderModel
import logging

logger = logging.getLogger(__name__)

def generate_financial_scorecard(db: Session, supplier_id: str):
    """
    Analyzes historical purchase orders to calculate exactly how much money 
    the pharmacy lost because this distributor failed to deliver on time or in full.
    """
    # 1. Fetch all completed or partial orders for this supplier
    orders = db.query(PurchaseOrderModel).filter(
        PurchaseOrderModel.supplier_id == supplier_id,
        PurchaseOrderModel.status.in_(["DELIVERED", "PARTIAL", "FAILED"])
    ).all()
    
    if not orders:
        return None

    total_orders = len(orders)
    on_time_count = 0
    total_shortfall_items = 0
    total_financial_loss = 0.0

    # 2. Loop through every order and calculate the damages
    for order in orders:
        # Check if it was delivered on time
        if order.actual_delivery_date and order.actual_delivery_date <= order.expected_delivery_date:
            on_time_count += 1
            
        # Calculate Shortfall (How many boxes were missing?)
        # Beginner Note: If we ordered 100 but got 80, the shortfall is 20.
        shortfall = max(0, order.ordered_qty - order.delivered_qty)
        total_shortfall_items += shortfall
        
        # Calculate Financial Loss (Lost Profit)
        # Beginner Note: Profit per box = (MRP - Cost). 
        # Total Loss = Missing Boxes * Profit per box.
        margin_per_unit = float(order.expected_mrp - order.cost_price)
        lost_profit = shortfall * margin_per_unit
        
        total_financial_loss += lost_profit

    # 3. Calculate the On-Time Delivery (OTIF) Rate
    on_time_rate = (on_time_count / total_orders) * 100

    # 4. Generate a negotiation recommendation based on the data
    if on_time_rate < 80.0 or total_financial_loss > 5000:
        recommendation = "CRITICAL: High financial loss. Renegotiate SLA terms or switch to a secondary distributor."
    elif total_shortfall_items > 0:
        recommendation = "WARNING: Frequent shortfalls detected. Request priority allocation for fast-moving goods."
    else:
        recommendation = "HEALTHY: Distributor is reliable. Maintain current relationship."

    return {
        "supplier_id": supplier_id,
        "total_orders_analyzed": total_orders,
        "on_time_delivery_rate": round(on_time_rate, 2),
        "total_shortfall_items": total_shortfall_items,
        "financial_loss_rupees": round(total_financial_loss, 2),
        "recommendation": recommendation
    }
