"""Machine Learning Mock Service.

Simulates the output of the Temporal Fusion Transformer (TFT) for Phase 1 MVP testing.
"""

import random
from typing import Any, Dict


def generate_mock_stockout_prediction(
    supplier_id_string: str,
    current_inventory: int,
    delivery_delay: int,
) -> Dict[str, Any]:
    """Simulates an ML model evaluating inventory levels and delivery delays to predict stockout risks.

    Args:
        supplier_id_string: The unique identifier for the supplier.
        current_inventory: The current stock count.
        delivery_delay: Number of days the last delivery was delayed.

    Returns:
        A dictionary containing the raw, unvalidated prediction outputs.
    """
    base_risk = 0.1
    if current_inventory < 50:
        base_risk = base_risk + 0.4
    if delivery_delay > 5:
        base_risk = base_risk + 0.3

    simulated_probability = base_risk + random.uniform(0.01, 0.1)

    final_probability = min(max(simulated_probability, 0.0), 1.0)

    is_risk_critical = True if final_probability > 0.75 else False

    raw_prediction_dictionary = {
        "supplier_id": supplier_id_string,
        "predicted_stockout_probability": final_probability,
        "is_critical_risk": is_risk_critical,
        "compliance_region": "INDIA_DPDP",
    }

    return raw_prediction_dictionary