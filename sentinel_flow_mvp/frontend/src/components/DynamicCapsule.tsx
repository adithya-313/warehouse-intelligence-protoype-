"use client";

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
          initial={{ opacity: 0, scale: 0.85, y: -20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.85, y: -20 }}
          transition={{ type: 'spring', stiffness: 350, damping: 30 }}
          className="fixed top-8 left-0 right-0 mx-auto w-max z-[100] rounded-full px-6 py-3 flex items-center gap-4 bg-[#0a0a0a]/70 backdrop-blur-2xl border border-white/10 shadow-[0_20px_40px_-10px_rgba(0,0,0,0.8),0_0_20px_rgba(255,255,255,0.03)]"
        >
          <div className="flex items-center justify-center w-6 h-6 rounded-full text-white">
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
            <span className="text-sm font-bold text-white/90 leading-tight">
              Checkout Complete
            </span>
            <span className="text-xs font-medium text-white/50 leading-tight">
              Receipt: {receiptId}
            </span>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
