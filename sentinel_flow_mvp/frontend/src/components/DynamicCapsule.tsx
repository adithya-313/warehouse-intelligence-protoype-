import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';

interface DynamicCapsuleProps {
  isOpen: boolean;
  receiptId: string;
}

export function DynamicCapsule({ isOpen, receiptId }: DynamicCapsuleProps) {
  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0, scale: 0.8, y: -20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.8, y: -10 }}
          transition={{ type: 'spring', stiffness: 400, damping: 25 }}
          className="fixed top-6 left-1/2 -translate-x-1/2 z-[100] flex items-center gap-3 px-5 py-3 rounded-full bg-emerald-950/40 backdrop-blur-xl border border-emerald-500/20 shadow-[0_0_40px_-10px_rgba(16,185,129,0.3)]"
        >
          <div className="flex items-center justify-center w-6 h-6 rounded-full bg-emerald-500/10 text-emerald-400">
            <svg
              className="w-4 h-4"
              fill="none"
              strokeWidth="3"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <motion.path
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.5, delay: 0.2, ease: "easeOut" }}
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M5 13l4 4L19 7"
              />
            </svg>
          </div>
          
          <div className="flex flex-col whitespace-nowrap">
            <span className="text-sm font-bold text-emerald-50 leading-tight">
              Checkout Complete
            </span>
            <span className="text-xs font-medium text-emerald-400/70 leading-tight">
              Receipt: {receiptId}
            </span>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
