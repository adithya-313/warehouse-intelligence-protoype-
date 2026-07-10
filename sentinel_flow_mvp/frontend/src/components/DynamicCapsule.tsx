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
          initial={{ y: -100, opacity: 0, scale: 0.8, x: '-50%' }}
          animate={{ y: 0, opacity: 1, scale: 1, x: '-50%' }}
          exit={{ y: -100, opacity: 0, scale: 0.8, x: '-50%' }}
          transition={{ type: 'spring', damping: 20, stiffness: 300 }}
          className="fixed top-6 left-1/2 z-[100] flex items-center gap-3 px-5 py-3 rounded-full bg-white/70 dark:bg-black/70 backdrop-blur-md border border-slate-200/50 dark:border-slate-800/50 shadow-lg"
        >
          <div className="flex items-center justify-center w-6 h-6 rounded-full bg-emerald-500/10 text-emerald-500">
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
          
          <motion.div
            initial={{ opacity: 0, width: 0 }}
            animate={{ opacity: 1, width: 'auto' }}
            transition={{ duration: 0.3, delay: 0.4 }}
            className="flex flex-col overflow-hidden whitespace-nowrap"
          >
            <span className="text-sm font-bold text-slate-900 dark:text-white leading-tight">
              Checkout Complete
            </span>
            <span className="text-xs font-medium text-slate-500 dark:text-slate-400 leading-tight">
              Receipt: {receiptId}
            </span>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
