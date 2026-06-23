import { CartItem } from '../store/posStore';

// Beginner Note: This function takes our frontend cart and sends it to the FastAPI backend.
// The backend will then instantly publish these to the Kafka Event Mesh.
export async function checkoutCart(cart: CartItem[], pharmacyLocation: string) {
  const promises = cart.map(item => {
    const payload = {
      transaction_id: `TXN-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
      batch_id: item.batch_id,
      sku_id: item.sku_id,
      quantity_sold: item.quantity,
      pharmacy_location: pharmacyLocation
    };

    return fetch('/api/v1/pos/sell', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
  });

  // Wait for all items to be sent to the backend
  await Promise.all(promises);
}
