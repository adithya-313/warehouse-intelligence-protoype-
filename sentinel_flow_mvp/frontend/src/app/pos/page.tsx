"use client";

import React, { useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { Search, ScanLine, Bot, Settings, BarChart3, CreditCard } from 'lucide-react';
import { cn } from '@/lib/utils';
import { usePOSStore } from '@/store/posStore';
import CopilotPanel from '@/components/pos/CopilotPanel';

export default function POSDashboard() {
  const [searchQuery, setSearchQuery] = useState('');
  const toggleCopilot = usePOSStore((state: any) => state.toggleCopilot);
  const cart = usePOSStore((state: any) => state.cart) || [];
  
  const totalAmount = cart.reduce((sum: number, item: any) => sum + (item.price * item.quantity), 0);

  return (
    <div className="relative min-h-screen bg-[#05050A] text-white overflow-hidden font-sans selection:bg-cyan-500/30">
      
      {/* GPU-ACCELERATED AMBIENT ORBS */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none flex items-center justify-center z-0">
        <motion.div 
          animate={{ rotate: 360, scale: [1, 1.1, 1] }} 
          transition={{ duration: 25, repeat: Infinity, ease: "linear" }}
          className="absolute w-[800px] h-[800px] bg-cyan-500/5 blur-[150px] rounded-full will-change-transform translate-x-1/3 -translate-y-1/4" 
        />
        <motion.div 
          animate={{ rotate: -360, scale: [1, 1.2, 1] }} 
          transition={{ duration: 30, repeat: Infinity, ease: "linear" }}
          className="absolute w-[600px] h-[600px] bg-fuchsia-500/5 blur-[150px] rounded-full will-change-transform -translate-x-1/3 translate-y-1/4" 
        />
      </div>

      {/* MAIN LAYOUT */}
      <div className="relative z-10 max-w-[1600px] mx-auto p-6 h-screen flex flex-col">
        
        {/* HEADER */}
        <header className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-white">Sentinel POS</h1>
            <div className="flex items-center gap-2 mt-1">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
              <span className="text-xs font-medium text-emerald-400 uppercase tracking-widest">Kafka Mesh Online</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button 
              onClick={toggleCopilot}
              className="px-4 py-2 bg-cyan-500/10 hover:bg-cyan-500/20 border border-cyan-500/30 text-cyan-400 rounded-xl text-sm font-semibold transition-all flex items-center gap-2 shadow-[0_0_15px_rgba(6,182,212,0.15)]"
            >
              <Bot size={16} /> Ask Copilot
            </button>
            <Link 
              href="/suppliers" 
              className="px-4 py-2 bg-white/[0.03] hover:bg-white/[0.08] border border-white/[0.05] text-slate-300 rounded-xl text-sm font-semibold transition-all flex items-center gap-2"
            >
              <BarChart3 size={16} /> Vendor Intelligence
            </Link>
            <Link 
              href="/admin/settings" 
              className="p-2 bg-white/[0.03] hover:bg-white/[0.08] border border-white/[0.05] text-slate-400 hover:text-white rounded-xl transition-all"
            >
              <Settings size={18} />
            </Link>
          </div>
        </header>

        {/* TWO-COLUMN WORKSPACE */}
        <div className="flex-1 grid grid-cols-1 lg:grid-cols-12 gap-6 min-h-0">
          
          {/* LEFT COLUMN: SEARCH & SCANNER */}
          <div className="lg:col-span-8 flex flex-col gap-6">
            
            {/* Search Panel (Quantum Glass) */}
            <div className="bg-white/[0.02] backdrop-blur-xl border border-white/[0.05] rounded-[2rem] p-8 shadow-2xl">
              <h2 className="text-lg font-semibold text-white flex items-center gap-2 mb-4">
                <Search size={20} className="text-slate-400" /> Manual Entry
              </h2>
              <div className="flex gap-3">
                <input 
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Type barcode or medicine name..."
                  className="flex-1 bg-black/40 border border-white/[0.1] rounded-xl px-5 py-4 text-white font-mono text-sm focus:outline-none focus:border-cyan-400/50 focus:ring-1 focus:ring-cyan-400/50 transition-all placeholder-white/20"
                />
                <button className="px-8 py-4 bg-white/10 hover:bg-white/20 border border-white/10 rounded-xl font-semibold transition-all">
                  Add
                </button>
              </div>

              {/* Sleek Global Scanner Status */}
              <div className="mt-6 bg-cyan-500/5 border border-cyan-500/20 rounded-xl p-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-cyan-500/20 rounded-lg">
                    <ScanLine className="w-5 h-5 text-cyan-400" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-white">Hardware Scanner Active</h3>
                    <p className="text-xs text-slate-400">Global listener enabled. Scan any barcode instantly.</p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-cyan-400 uppercase tracking-wider">Ready</span>
                </div>
              </div>
            </div>

            {/* Inventory / Quick Add Area (Placeholder for future) */}
            <div className="flex-1 bg-white/[0.01] border border-white/[0.02] rounded-[2rem] flex items-center justify-center">
              <p className="text-slate-600 text-sm font-mono uppercase tracking-widest">Awaiting Telemetry</p>
            </div>
          </div>

          {/* RIGHT COLUMN: CART */}
          <div className="lg:col-span-4 bg-white/[0.02] backdrop-blur-xl border border-white/[0.05] rounded-[2rem] flex flex-col shadow-2xl overflow-hidden">
            <div className="p-6 border-b border-white/[0.05]">
              <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                Current Order
              </h2>
            </div>
            
            <div className="flex-1 p-6 overflow-y-auto">
              {cart.length === 0 ? (
                <div className="h-full flex items-center justify-center text-slate-500 text-sm">
                  Cart is empty. Scan an item to begin.
                </div>
              ) : (
                <div className="space-y-4">
                  {/* Cart items would map here */}
                </div>
              )}
            </div>

            <div className="p-6 bg-black/40 border-t border-white/[0.05]">
              <div className="flex justify-between items-end mb-6">
                <span className="text-slate-400 text-sm font-medium">Total Amount</span>
                <span className="text-4xl font-black text-white tracking-tight">₹{totalAmount.toFixed(2)}</span>
              </div>
              <button 
                disabled={cart.length === 0}
                className="w-full py-4 bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/50 text-emerald-400 rounded-xl font-bold transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <CreditCard size={18} /> Complete Transaction
              </button>
            </div>
          </div>

        </div>
      </div>

      {/* COPILOT OVERLAY */}
      <CopilotPanel />
    </div>
  );
}
