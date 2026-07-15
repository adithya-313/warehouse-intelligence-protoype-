// [STORY: THE STOCK PULSE UI]
// This component is designed with psychological brilliance. 
// It doesn't just display a boring number. It uses color and motion to communicate urgency.
// - Healthy Stock (> 10): Calm Green, no animation. Assures the pharmacist all is well.
// - Low Stock (1 - 10): Warning Orange. 
// - Critical/Empty (0): Pulsing Red. Creates immediate visual urgency to reorder.

import React, { useEffect, useState } from 'react';
import { api } from '../services/api';

interface StockPulseProps {
  skuId: string;
}

export const StockPulse: React.FC<StockPulseProps> = ({ skuId }) => {
  const [stockInfo, setStockInfo] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  // Scene 1: Fetching the truth from our projection API
  useEffect(() => {
    const fetchStock = async () => {
      try {
        const data = await api.get(`/api/v1/inventory/projection/${skuId}`);
        setStockInfo(data);
      } catch (error) {
        console.error("Failed to read stock pulse", error);
      } finally {
        setLoading(false);
      }
    };
    
    fetchStock();
    // In a real high-frequency environment, we might poll this every 10 seconds
    const interval = setInterval(fetchStock, 10000); 
    return () => clearInterval(interval);
  }, [skuId]);

  if (loading) return <div className="text-gray-400 animate-pulse">Scanning shelves...</div>;

  // Scene 2: Applying Psychological UI Rules
  const available = stockInfo?.true_available_stock || 0;
  let colorClass = "text-green-500";
  let pulseClass = "";
  let message = "Stock Healthy";

  if (available <= 0) {
    colorClass = "text-red-600 font-bold";
    pulseClass = "animate-pulse"; // Urgency!
    message = "OUT OF STOCK - DO NOT PRESCRIBE";
  } else if (available <= 5) {
    colorClass = "text-orange-500";
    message = "Low Stock - Reorder Soon";
  }

  // Scene 3: The Render
  return (
    <div className={`p-4 rounded-lg border border-gray-800 bg-gray-900 ${pulseClass}`}>
      <h3 className="text-sm uppercase tracking-widest text-gray-400 mb-1">Live Inventory Pulse</h3>
      <div className="flex items-end space-x-2">
        <span className={`text-4xl ${colorClass}`}>{available}</span>
        <span className="text-gray-500 mb-1">units available</span>
      </div>
      <p className={`text-xs mt-2 ${colorClass}`}>{message}</p>
      
      {/* Transparency for the user: Show them WHY the number is what it is */}
      {stockInfo?.locked_in_carts > 0 && (
        <p className="text-xs text-blue-400 mt-1">
          Note: {stockInfo.locked_in_carts} units are currently locked in active checkouts.
        </p>
      )}
    </div>
  );
};
