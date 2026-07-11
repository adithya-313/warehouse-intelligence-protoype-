"use client";

import React, { useState, MouseEvent } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import type { TransactionHistoryItem, PaymentMethod } from '@/services/api';

interface LedgerRowProps {
  transaction: TransactionHistoryItem;
  isExpanded: boolean;
  onToggle: () => void;
}

const paymentBadge: Record<PaymentMethod, { bg: string; text: string; label: string }> = {
  CASH: { bg: 'bg-emerald-50', text: 'text-emerald-700', label: 'Cash' },
  UPI: { bg: 'bg-blue-50', text: 'text-blue-700', label: 'UPI' },
  CARD: { bg: 'bg-violet-50', text: 'text-violet-700', label: 'Card' },
};

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
export default function LedgerRow({ transaction, isExpanded, onToggle }: LedgerRowProps) {
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

  const badge = paymentBadge[transaction.payment_method];

  return (
    <>
      <motion.tr
        onClick={onToggle}
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
        className="border-b border-slate-100/50 last:border-0 cursor-pointer"
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

      {/* Fluid Inline Accordion */}
      <AnimatePresence>
        {isExpanded && (
          <motion.tr
            key={`${transaction.id}-expanded`}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: "easeInOut" }}
            className="overflow-hidden"
          >
            <td colSpan={5} className="p-0">
              <div className="bg-slate-50 border-t border-slate-100 p-6">
                {/* Method Badge */}
                <div className="flex items-center gap-3 mb-4">
                  <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold ${badge.bg} ${badge.text}`}>
                    {badge.label}
                  </span>
                  <span className="text-xs text-slate-400 font-mono">{transaction.id}</span>
                </div>

                {/* Items List */}
                <div className="space-y-2">
                  {transaction.items.map((item, idx) => (
                    <div key={idx} className="flex items-center justify-between text-sm">
                      <span className="text-slate-600 truncate max-w-md">{item.name}</span>
                      <div className="flex items-center gap-4 flex-shrink-0">
                        <span className="text-slate-400">x{item.quantity}</span>
                        <span className="text-slate-900 font-medium w-20 text-right">₹{item.total.toFixed(2)}</span>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Total */}
                <div className="flex items-center justify-between pt-3 mt-3 border-t border-slate-200/60 text-sm">
                  <span className="font-semibold text-slate-700">Total</span>
                  <span className="font-bold text-slate-900">₹{transaction.total_amount_inr.toFixed(2)}</span>
                </div>
              </div>
            </td>
          </motion.tr>
        )}
      </AnimatePresence>
    </>
  );
}
