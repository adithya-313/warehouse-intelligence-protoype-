"use client";

import React, { useState } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, Bot, Settings, BarChart3, ShoppingBag, ArrowRight, Barcode, ScanLine } from 'lucide-react';
import { cn } from '@/lib/utils';
import { usePOSStore } from '@/store/posStore';
import CopilotPanel from '@/components/pos/CopilotPanel';

export default function POSDashboard() {
  const [searchQuery, setSearchQuery] = useState('');
  const toggleCopilot = usePOSStore((state: any) => state.toggleCopilot);
  const cart = usePOSStore((state: any) => state.cart) || [];
  
  const totalAmount = cart.reduce((sum: number, item: any) => sum + (item.price * item.quantity), 0);

  return (
    <div className="relative min-h-screen bg-[#fdfbfb] text-slate-800 overflow-hidden selection:bg-blue-100">
      
      {/* ETHEREAL BIOLOGICAL ORBS (GPU Accelerated) */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none flex items-center justify-center z-0">
        <motion.div 
          animate={{ rotate: 360, scale: [1, 1.05, 1] }} 
          transition={{ duration: 30, repeat: Infinity, ease: "linear" }}
          className="absolute w-[800px] h-[800px] bg-rose-100/50 blur-[120px] rounded-full will-change-transform translate-x-1/4 -translate-y-1/4 mix-blend-multiply" 
        />
        <motion.div 
          animate={{ rotate: -360, scale: [1, 1.1, 1] }} 
          transition={{ duration: 40, repeat: Infinity, ease: "linear" }}
          className="absolute w-[600px] h-[600px] bg-blue-100/50 blur-[120px] rounded-full will-change-transform -translate-x-1/4 translate-y-1/4 mix-blend-multiply" 
        />
        <motion.div 
          animate={{ scale: [1, 1.2, 1], opacity: [0.4, 0.6, 0.4] }} 
          transition={{ duration: 20, repeat: Infinity, ease: "easeInOut" }}
          className="absolute w-[500px] h-[500px] bg-amber-50/60 blur-[100px] rounded-full will-change-transform mix-blend-multiply" 
        />
      </div>

      {/* MAIN LAYOUT */}
      <div className="relative z-10 max-w-[1600px] mx-auto p-6 md:p-8 h-screen flex flex-col">
        
        {/* FLOATING HEADER */}
        <motion.header 
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex justify-between items-center mb-8 bg-white/40 backdrop-blur-2xl border border-white/80 shadow-[0_4px_24px_rgba(0,0,0,0.02)] rounded-3xl px-6 py-4"
        >
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-slate-800 to-slate-900 rounded-xl flex items-center justify-center shadow-md">
              <ShoppingBag className="text-white w-5 h-5" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">Sentinel</h1>
          </div>

          <div className="flex items-center gap-3">
            <motion.button 
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={toggleCopilot}
              className="px-5 py-2.5 bg-blue-50/80 hover:bg-blue-100 border border-blue-200/50 text-blue-600 rounded-2xl text-sm font-semibold transition-colors flex items-center gap-2 shadow-sm"
            >
              <Bot size={18} /> Clinical Copilot
            </motion.button>
            <Link href="/suppliers">
              <motion.button 
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                className="px-5 py-2.5 bg-white/60 hover:bg-white border border-gray-200/50 text-slate-600 rounded-2xl text-sm font-semibold transition-colors flex items-center gap-2 shadow-sm"
              >
                <BarChart3 size={18} /> Vendors
              </motion.button>
            </Link>
            <Link href="/admin/settings">
              <motion.button 
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                className="p-2.5 bg-white/60 hover:bg-white border border-gray-200/50 text-slate-400 hover:text-slate-600 rounded-2xl transition-colors shadow-sm"
              >
                <Settings size={20} />
              </motion.button>
            </Link>
          </div>
        </motion.header>

        {/* TWO-COLUMN WORKSPACE */}
        <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-8 min-h-0">
          
          {/* LEFT COLUMN: SEARCH & INVENTORY */}
          <motion.div 
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.1 }}
            className="lg:col-span-8 flex flex-col gap-8"
          >
            {/* Massive, Elegant Search Bar */}
            <div className="relative group">
              <div className="absolute inset-0 bg-gradient-to-r from-blue-100 to-rose-100 rounded-[2rem] blur-xl opacity-50 group-hover:opacity-70 transition-opacity duration-500"></div>
              <div className="relative bg-white/80 backdrop-blur-3xl border border-white shadow-[0_8px_32px_rgba(0,0,0,0.04)] rounded-[2rem] p-4 flex items-center gap-4 transition-all focus-within:ring-4 focus-within:ring-blue-100 focus-within:border-blue-300">
                <div className="p-4 bg-slate-50 rounded-2xl text-slate-400">
                  <Search size={24} />
                </div>
                <input 
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Scan barcode or type medicine name..."
                  className="flex-1 bg-transparent border-none text-xl text-slate-800 placeholder-slate-300 focus:outline-none focus:ring-0 font-medium"
                />
                {/* Subtle Scanner Indicator */}
                <div className="flex items-center gap-2 px-4 py-2 bg-emerald-50/50 rounded-xl border border-emerald-100/50">
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
                  </span>
                  <Barcode size={16} className="text-emerald-600" />
                </div>
              </div>
            </div>

            {/* Empty State / Inventory Area */}
            <div className="flex-1 bg-white/40 backdrop-blur-xl border border-white/80 shadow-[0_8px_32px_rgba(0,0,0,0.02)] rounded-[2rem] flex flex-col items-center justify-center text-center p-10">
              <div className="w-20 h-20 bg-slate-50 rounded-3xl flex items-center justify-center mb-6 shadow-inner border border-slate-100">
                <ScanLine size={32} className="text-slate-300" />
              </div>
              <h3 className="text-xl font-semibold text-slate-700 mb-2">Ready for next patient</h3>
              <p className="text-slate-400 max-w-sm">The system is listening. Scan a product to instantly add it to the active transaction.</p>
            </div>
          </motion.div>

          {/* RIGHT COLUMN: THE RECEIPT (CART) */}
          <motion.div 
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.2 }}
            className="lg:col-span-4 bg-white/70 backdrop-blur-3xl border border-white shadow-[0_16px_48px_rgba(0,0,0,0.05)] rounded-[2.5rem] flex flex-col overflow-hidden relative"
          >
            <div className="p-8 border-b border-slate-100/50">
              <h2 className="text-xl font-bold text-slate-800 tracking-tight">Current Order</h2>
            </div>
            
            <div className="flex-1 p-8 overflow-y-auto">
              <AnimatePresence mode="popLayout">
                {cart.length === 0 ? (
                  <motion.div 
                    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                    className="h-full flex flex-col items-center justify-center text-slate-400"
                  >
                    <ShoppingBag size={48} className="mb-4 opacity-20" />
                    <p className="font-medium">Cart is empty</p>
                  </motion.div>
                ) : (
                  <div className="space-y-4">
                    {/* Cart items would map here with layout animations */}
                  </div>
                )}
              </AnimatePresence>
            </div>

            {/* Checkout Footer */}
            <div className="p-8 bg-white/80 backdrop-blur-md border-t border-slate-100/50">
              <div className="flex justify-between items-end mb-6">
                <span className="text-slate-500 font-medium">Total Amount</span>
                <span className="text-5xl font-black text-slate-900 tracking-tighter">₹{totalAmount.toFixed(2)}</span>
              </div>
              <motion.button 
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                disabled={cart.length === 0}
                className="w-full py-5 bg-slate-900 hover:bg-slate-800 text-white rounded-2xl font-bold text-lg transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed shadow-xl shadow-slate-900/20"
              >
                Complete Checkout <ArrowRight size={20} />
              </motion.button>
            </div>
          </motion.div>

        </div>
      </div>

      {/* COPILOT OVERLAY */}
      <CopilotPanel />
    </div>
  );
}
