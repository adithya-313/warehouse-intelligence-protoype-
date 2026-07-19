"""
[STORY: THE DELIVERY TRUCK ARRIVES]
We query the database for pending POs and simulate a delivery that is
3 days late and missing 20% of its inventory to trigger the Trust Score penalty.
"""

from datetime import datetime, timedelta
import requests

API_URL = "http://localhost:8080/api/v1"


def simulate_intake():
    print("Delivery Truck Arriving...")

    po_id = input("Enter the PO-ID you just generated (e.g., PO-1234ABCD): ").strip()

    if not po_id:
        print("PO ID required. Aborting.")
        return

    arrival_date = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")

    payload = {
        "po_id": po_id,
        "actual_delivery_date": arrival_date,
        "items": [
            {"sku_id": "AMOX500", "delivered_qty": 50},
            {"sku_id": "PAN40", "delivered_qty": 0},
        ],
    }

    print(f"Scanning received goods for {po_id}...")
    response = requests.post(f"{API_URL}/purchase-orders/receive", json=payload)

    if response.status_code == 200:
        print("Intake successful! State transitioned to FULFILLED.")
        print("Check the Frontend Dashboard. The vendor's Trust Score should have dropped.")
    else:
        print(f"Intake failed: {response.text}")


if __name__ == "__main__":
    simulate_intake()
