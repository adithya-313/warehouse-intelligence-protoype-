"use client";

import React, { ReactNode } from 'react';
import { motion } from 'framer-motion';

interface TransactionMatrixProps {
  children: ReactNode;
}

/**
 * TransactionMatrix
 * 
 * The structural chassis for the Ledger UI.
 * 
 * Aesthetics:
 * We encapsulate the raw table data inside a pristine glassmorphic shell.
 * The `backdrop-blur-3xl` and `bg-white/[0.02]` create an icy, frosted 
 * transparency that reacts beautifully with the ScreenAtmosphere grain behind it.
 * 
 * Animation (The Waterfall Reveal):
 * Using Framer Motion's `staggerChildren`, we instruct the wrapper to wait 
 * briefly before animating each child row. This prevents all data rows from 
 * smashing into view at once, producing a highly satisfying cascading entrance.
 * 
 * @param children - The mapped array of `<LedgerRow />` components.
 */
export default function TransactionMatrix({ children }: TransactionMatrixProps) {
  return (
    <div className="w-full rounded-2xl bg-white/[0.02] backdrop-blur-3xl border border-white/10 shadow-2xl p-6 overflow-hidden">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr>
            <th className="text-xs font-semibold text-gray-400 tracking-wider uppercase border-b border-white/10 pb-4 px-6">
              Date / Time
            </th>
            <th className="text-xs font-semibold text-gray-400 tracking-wider uppercase border-b border-white/10 pb-4 px-6">
              Receipt ID
            </th>
            <th className="text-xs font-semibold text-gray-400 tracking-wider uppercase border-b border-white/10 pb-4 px-6">
              Customer Name
            </th>
            <th className="text-xs font-semibold text-gray-400 tracking-wider uppercase border-b border-white/10 pb-4 px-6">
              Phone Number
            </th>
            <th className="text-xs font-semibold text-gray-400 tracking-wider uppercase border-b border-white/10 pb-4 px-6 text-right">
              Total Amount
            </th>
          </tr>
        </thead>
        
        {/* 
          We render the tbody as a motion element so it can act as the orchestration 
          parent for the staggered child row entrances.
        */}
        <motion.tbody
          initial="hidden"
          animate="visible"
          variants={{
            hidden: {}, // Base initial state
            visible: {
              transition: {
                staggerChildren: 0.05, // 50ms delay between each row's entrance
              }
            }
          }}
        >
          {children}
        </motion.tbody>
      </table>
    </div>
  );
}
