"use client";

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, Bot, Settings, BarChart3, ShoppingBag, ArrowRight, Barcode, ScanLine } from 'lucide-react';
import { cn } from '@/lib/utils';
import { usePOSStore } from '@/store/posStore';
import CopilotPanel from '@/components/pos/CopilotPanel';
import { PreemptiveWarningBanner } from "@/components/PreemptiveWarningBanner";
import { NotificationBell } from "@/components/NotificationBell";
import { api } from '@/services/api';

export default function POSDashboard() {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const toggleCopilot = usePOSStore((state: any) => state.toggleCopilot);
  const cart = usePOSStore((state: any) => state.cart) || [];
  const addItem = usePOSStore((state: any) => state.addItem);
  const removeItem = usePOSStore((state: any) => state.removeItem);
  
  const totalAmount = cart.reduce((sum: number, item: any) => sum + (item.price * item.quantity), 0);

  useEffect(() => {
    if (searchQuery.trim().length < 2) {
      setSearchResults([]);
      return;
    }

    setIsSearching(true);
    const delayDebounceFn = setTimeout(() => {
      api.searchInventory(searchQuery)
        .then((data) => {
          setSearchResults(data);
        })
        .catch((err) => {
          console.error("Search failed:", err);
          setSearchResults([]);
        })
        .finally(() => {
          setIsSearching(false);
        });
    }, 300);

    return () => clearTimeout(delayDebounceFn);
  }, [searchQuery]);

  return (
    <div className="relative min-h-screen bg-[#fdfbfb] text-slate-800 selection:bg-blue-100">
      
      {/* ETHEREAL BIOLOGICAL ORBS */}
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
          className="relative z-50 flex justify-between items-center mb-8 bg-white/40 backdrop-blur-2xl border border-white/80 shadow-[0_4px_24px_rgba(0,0,0,0.02)] rounded-3xl px-6 py-4"
        >
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-gradient-to-br from-slate-800 to-slate-900 rounded-xl flex items-center justify-center shadow-md">
              <ShoppingBag className="text-white w-5 h-5" />
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">Sentinel</h1>
          </div>

          <div className="flex items-center gap-3">
            <NotificationBell />
            {/* DESIGN TOKEN: Neural Pulse (AI Button) */}
            <motion.button 
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.98 }}
              onClick={toggleCopilot}
              className="relative px-5 py-2.5 rounded-2xl text-sm font-bold transition-all flex items-center gap-2 overflow-hidden group shadow-sm border border-white/50"
            >
              <motion.div 
                animate={{ backgroundPosition: ["0% center", "200% center"] }}
                transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
                className="absolute inset-0 bg-gradient-to-r from-cyan-500/10 via-violet-500/10 to-cyan-500/10 bg-[length:200%_auto]"
              />
              <Bot size={18} className="text-cyan-600 relative z-10" /> 
              <span className="bg-gradient-to-r from-cyan-700 to-violet-700 bg-clip-text text-transparent relative z-10">Clinical Copilot</span>
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

        {/* PREEMPTIVE BANNER */}
        <PreemptiveWarningBanner />

        {/* TWO-COLUMN WORKSPACE */}
        <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-8 min-h-0">
          
          {/* LEFT COLUMN: SEARCH & INVENTORY */}
          <motion.div 
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.1 }}
            className="lg:col-span-8 flex flex-col gap-8"
          >
            {/* DESIGN TOKEN: Iridescent Pearl Wrapper (Search Bar) */}
            <div className="relative group rounded-[2rem] p-[1px] bg-gradient-to-br from-blue-200/50 via-rose-200/50 to-amber-200/50 shadow-[0_8px_32px_rgba(0,0,0,0.04)]">
              <div className="relative bg-white/80 backdrop-blur-3xl rounded-[calc(2rem-1px)] p-4 flex items-center gap-4 transition-all focus-within:bg-white/90">
                <div className="p-4 bg-slate-50 rounded-2xl text-slate-400 shadow-inner border border-slate-100/50">
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

              {/* SEARCH RESULTS DROPDOWN */}
              <AnimatePresence>
                {isSearching && (
                  <motion.div
                    initial={{ opacity: 0, y: 10, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: 10, scale: 0.98 }}
                    className="absolute left-0 right-0 mt-2 bg-white/95 backdrop-blur-xl border border-slate-100 shadow-[0_16px_48px_rgba(0,0,0,0.08)] rounded-2xl z-50 p-4 text-center text-slate-400 text-sm"
                  >
                    Searching...
                  </motion.div>
                )}

                {!isSearching && searchQuery.trim().length >= 2 && searchResults.length === 0 && (
                  <motion.div
                    initial={{ opacity: 0, y: 10, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: 10, scale: 0.98 }}
                    className="absolute left-0 right-0 mt-2 bg-white/95 backdrop-blur-xl border border-slate-100 shadow-[0_16px_48px_rgba(0,0,0,0.08)] rounded-2xl z-50 p-4 text-center text-slate-400 text-sm"
                  >
                    No medications found matching "{searchQuery}"
                  </motion.div>
                )}

                {!isSearching && searchResults.length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, y: 10, scale: 0.98 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, y: 10, scale: 0.98 }}
                    transition={{ duration: 0.2 }}
                    className="absolute left-0 right-0 mt-2 bg-white/95 backdrop-blur-xl border border-slate-100 shadow-[0_16px_48px_rgba(0,0,0,0.08)] rounded-2xl z-50 overflow-hidden max-h-60 overflow-y-auto"
                  >
                    {searchResults.map((item) => (
                      <div
                        key={item.batch_id}
                        onClick={() => {
                          addItem({
                            batch_id: item.batch_id,
                            sku_id: item.sku_id,
                            name: item.name,
                            price: item.price
                          });
                          setSearchQuery('');
                          setSearchResults([]);
                        }}
                        className="flex justify-between items-center p-4 hover:bg-slate-50 cursor-pointer transition-colors border-b border-slate-50 last:border-none"
                      >
                        <div>
                          <div className="font-bold text-slate-800 text-sm">{item.name}</div>
                          <div className="text-xs text-slate-400">Batch: {item.batch_id} | Location: {item.shelf_location || "UNASSIGNED"}</div>
                        </div>
                        <div className="text-right">
                          <div className="font-semibold text-slate-900 text-sm">₹{item.price.toFixed(2)}</div>
                          <div className="text-xs text-emerald-600 font-medium">{item.available_quantity} available</div>
                        </div>
                      </div>
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* Empty State / Inventory Area */}
            <div className="flex-1 rounded-[2rem] p-[1px] bg-gradient-to-br from-white/40 to-white/10">
              <div className="h-full w-full bg-white/40 backdrop-blur-xl rounded-[calc(2rem-1px)] flex flex-col items-center justify-center text-center p-10">
                <div className="w-20 h-20 bg-white/60 rounded-3xl flex items-center justify-center mb-6 shadow-sm border border-white">
                  <ScanLine size={32} className="text-slate-300" />
                </div>
                <h3 className="text-xl font-semibold text-slate-700 mb-2">Ready for next patient</h3>
                <p className="text-slate-400 max-w-sm">The system is listening. Scan a product to instantly add it to the active transaction.</p>
              </div>
            </div>
          </motion.div>

          {/* RIGHT COLUMN: THE RECEIPT (CART) */}
          {/* DESIGN TOKEN: Iridescent Pearl Wrapper (Cart) */}
          <motion.div 
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.2 }}
            className="lg:col-span-4 rounded-[2.5rem] p-[1px] bg-gradient-to-br from-blue-200/50 via-rose-200/50 to-amber-200/50 shadow-[0_16px_48px_rgba(0,0,0,0.05)] flex flex-col"
          >
            <div className="h-full w-full bg-white/70 backdrop-blur-3xl rounded-[calc(2.5rem-1px)] flex flex-col overflow-hidden relative">
              <div className="p-8 border-b border-slate-100/50">
                <h2 className="text-xl font-bold text-slate-800 tracking-tight">Current Order</h2>
              </div>
              
              <div className="flex-1 p-8 overflow-y-auto">
                <AnimatePresence mode="popLayout">
                  {!mounted || cart.length === 0 ? (
                    <motion.div 
                      initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                      className="h-full flex flex-col items-center justify-center text-slate-400"
                    >
                      <ShoppingBag size={48} className="mb-4 opacity-20" />
                      <p className="font-medium">Cart is empty</p>
                    </motion.div>
                  ) : (
                    <div className="space-y-4">
                      {cart.map((item: any) => (
                        <motion.div
                          key={item.batch_id}
                          layoutId={`cart-item-${item.batch_id}`}
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -10 }}
                          className="flex justify-between items-center bg-white/60 hover:bg-white/80 p-4 rounded-2xl border border-slate-100/50 shadow-sm transition-colors"
                        >
                          <div className="flex-1 min-w-0 pr-2">
                            <div className="font-bold text-slate-800 text-sm truncate">{item.name}</div>
                            <div className="text-[10px] text-slate-400 truncate">Batch: {item.batch_id}</div>
                            <div className="text-xs font-semibold text-slate-500 mt-1">
                              {item.quantity} × ₹{item.price.toFixed(2)}
                            </div>
                          </div>
                          <div className="flex items-center gap-3">
                            <span className="font-bold text-slate-900 text-sm whitespace-nowrap">
                              ₹{(item.price * item.quantity).toFixed(2)}
                            </span>
                            <button
                              onClick={() => removeItem(item.batch_id)}
                              className="p-1.5 hover:bg-rose-50 rounded-xl text-rose-500 hover:text-rose-700 transition-colors"
                              title="Remove Item"
                            >
                              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                              </svg>
                            </button>
                          </div>
                        </motion.div>
                      ))}
                    </div>
                  )}
                </AnimatePresence>
              </div>

              {/* Checkout Footer */}
              <div className="p-8 bg-white/80 backdrop-blur-md border-t border-slate-100/50">
                <div className="flex justify-between items-end mb-6">
                  <span className="text-slate-500 font-medium">Total Amount</span>
                  <span className="text-5xl font-black text-slate-900 tracking-tighter">₹{mounted ? totalAmount.toFixed(2) : "0.00"}</span>
                </div>
                
                {/* DESIGN TOKEN: Liquid Titanium (Checkout Button) */}
                <motion.button 
                  whileHover={{ scale: 1.02, backgroundPosition: "100% center" }}
                  whileTap={{ scale: 0.98 }}
                  disabled={!mounted || cart.length === 0}
                  className="w-full py-5 bg-gradient-to-r from-slate-900 via-slate-700 to-slate-900 bg-[length:200%_auto] text-white rounded-2xl font-bold text-lg transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed shadow-[inset_0_1px_1px_rgba(255,255,255,0.25),0_12px_24px_rgba(15,23,42,0.2)] border border-slate-800"
                >
                  Complete Checkout <ArrowRight size={20} />
                </motion.button>
              </div>
            </div>
          </motion.div>

        </div>
      </div>

      {/* COPILOT OVERLAY */}
      <CopilotPanel />
    </div>
  );
}
