// [STORY: THE CRITICAL STOCK OVERLAY]
// This system stays completely invisible under normal conditions.
// But if a pharmacist searches for a drug and the stock is below 50, 
// the entire screen dims and pulses red to immediately capture their attention.
// It is transient: it vanishes if they clear the search, change the search, or add it to the cart.

import React from 'react';

interface CriticalStockOverlayProps {
  stockCount: number;
  isVisible: boolean;
}

export const CriticalStockOverlay: React.FC<CriticalStockOverlayProps> = ({ stockCount, isVisible }) => {
  // Scene 1: The Invisible Guard
  // If the component is told to hide, or stock is 50 or above, render absolutely nothing.
  if (!isVisible || stockCount >= 50) return null;

  // Scene 2: The Full-Screen Flash
  // pointer-events-none ensures the pharmacist can still click the screen, 
  // type, or hit "Add to Cart" while the screen is flashing.
  return (
    <div className="fixed inset-0 z-50 pointer-events-none flex items-center justify-center bg-red-900/30 animate-pulse transition-opacity duration-300">
      <div className="bg-red-950 border-2 border-red-500 p-8 rounded-xl shadow-2xl flex flex-col items-center">
        <h2 className="text-red-500 text-3xl font-black uppercase tracking-widest mb-2">Critical Stock Warning</h2>
        <p className="text-white text-xl">
          Only <span className="font-bold text-red-400">{stockCount}</span> units left in inventory.
        </p>
        <p className="text-gray-400 text-sm mt-4 uppercase">Reorder immediately</p>
      </div>
    </div>
  );
};
