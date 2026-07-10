"use client";

import React, { useState, MouseEvent } from 'react';
import { motion } from 'framer-motion';
import type { TransactionHistoryItem } from '@/services/api';

interface LedgerRowProps {
  transaction: TransactionHistoryItem;
}

/**
 * LedgerRow
 * 
 * An interactive, kinetic transaction row for the Ledger Matrix.
 * 
 * The Spotlight Physics:
 * We listen to `onMouseMove` to calculate the exact cursor coordinates relative 
 * to this specific row. When hovered, we render a soft radial gradient at those 
 * coordinates directly onto the row's background. This creates a "spotlight" 
 * effect that follows the user's cursor, providing highly tactile feedback.
 * 
 * @param transaction - The transaction data object from the backend API.
 */
export default function LedgerRow({ transaction }: LedgerRowProps) {
  // We track the relative mouse coordinates for the spotlight effect
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [isHovering, setIsHovering] = useState(false);

  // Helper to format the raw ISO date into a readable string
  const formatDate = (isoString: string) => {
    const d = new Date(isoString);
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const month = months[d.getMonth()];
    const day = d.getDate();
    const year = d.getFullYear();
    const hours = d.getHours().toString().padStart(2, '0');
    const minutes = d.getMinutes().toString().padStart(2, '0');
    return `${month} ${day}, ${year} — ${hours}:${minutes}`;
  };

  /**
   * Captures the cursor position relative to the row itself.
   * `currentTarget.getBoundingClientRect()` gives us the exact bounds of the row,
   * allowing us to subtract the viewport offsets and isolate the local coordinates.
   */
  const handleMouseMove = (e: MouseEvent<HTMLTableRowElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    setMousePos({
      x: e.clientX - rect.left,
      y: e.clientY - rect.top,
    });
  };

  return (
    <motion.tr
      // 1. The Micro-Lift: A buttery 1% scale bump on hover
      whileHover={{ scale: 1.01 }}
      // 2. We use Framer Motion variants for the entrance stagger cascade
      variants={{
        hidden: { opacity: 0, y: 10 },
        visible: { opacity: 1, y: 0, transition: { type: "spring", stiffness: 300, damping: 24 } }
      }}
      // 3. Spotlight Events
      onMouseMove={handleMouseMove}
      onMouseEnter={() => setIsHovering(true)}
      onMouseLeave={() => setIsHovering(false)}
      // 4. Spotlight Background (Inline Style overrides Tailwind when active)
      style={{
        background: isHovering
          ? `radial-gradient(400px circle at ${mousePos.x}px ${mousePos.y}px, rgba(0,0,0,0.04), transparent 50%)`
          : 'transparent',
      }}
      className="border-b border-slate-100/50 last:border-0 cursor-default"
    >
      <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-700">
        {formatDate(transaction.timestamp)}
      </td>
      
      {/* 
        The Receipt ID is rendered in a monospace font to ensure perfectly 
        aligned vertical presentation of alphanumeric hashes.
      */}
      <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-900 font-mono">
        {transaction.id.split('-')[0]}...
      </td>
      
      <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-700">
        {transaction.customer_name === "Anonymous" ? (
          <span className="px-3 py-1 bg-slate-50 text-slate-400 rounded-full text-xs font-medium border border-slate-200/50">
            Anonymous
          </span>
        ) : (
          <span className="font-medium text-slate-800">{transaction.customer_name}</span>
        )}
      </td>
      
      <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-500">
        {transaction.customer_phone || "—"}
      </td>
      
      {/* 
        The monetary value demands high contrast. We anchor it to the right 
        for immediate numerical scannability.
      */}
      <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-bold text-slate-900 font-mono">
        ₹{transaction.total_amount_inr.toFixed(2)}
      </td>
    </motion.tr>
  );
}
