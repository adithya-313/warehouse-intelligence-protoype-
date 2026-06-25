"use client";

import React, { useState } from 'react';
import { usePOSStore } from '../../store/posStore';
import { useHardwareScanner } from '../../hooks/useHardwareScanner';
import { checkoutCart } from '../../services/posApi';
import { motion, AnimatePresence } from 'framer-motion';
import { Toaster, toast } from 'sonner';
import { ShoppingCart, ScanLine, Search, Trash2, CreditCard, Bot, BarChart3 } from 'lucide-react';
import Link from 'next/link';
import CopilotPanel from '@/components/pos/CopilotPanel';

export default function POSInterface() {
  const { cart, addItem, removeItem, clearCart, getTotal, isProcessing, setProcessing } = usePOSStore();
  const [manualInput, setManualInput] = useState('');

  // --- The Hardware Scanner Integration ---
  useHardwareScanner((barcode) => {
    // In a real app, you would fetch the item details from the DB using the barcode.
    // For this MVP, we mock the database lookup.
    const mockItem = {
      batch_id: `BATCH-${barcode}`,
      sku_id: `SKU-${barcode.substring(0, 4)}`,
      name: `Medication (${barcode})`,
      price: 15.99
    };
    addItem(mockItem);
    toast.success(`${mockItem.name} added to cart`);
  });

  // --- Manual Entry Handler ---
  const handleManualAdd = (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualInput) return;
    addItem({
      batch_id: `BATCH-${manualInput}`,
      sku_id: `SKU-MANUAL`,
      name: `Manual Entry (${manualInput})`,
      price: 10.00
    });
    toast.success(`Item added manually`);
    setManualInput('');
  };

  // --- Checkout Handler ---
  const handleCheckout = async () => {
    if (cart.length === 0) return;
    setProcessing(true);
    try {
      // Send to Kafka via FastAPI
      await checkoutCart(cart, "STORE-001");
      toast.success("Transaction Complete! Sent to Event Mesh.", {
        style: { background: '#10b981', color: 'white', border: 'none' }
      });
      clearCart();
    } catch (error) {
      toast.error("Checkout failed. Please try again.");
    } finally {
      setProcessing(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-200 font-sans selection:bg-emerald-500/30">
      {/* Beautiful Toast Notifications */}
      <Toaster position="top-center" theme="dark" />

      {/* Top Navigation Bar */}
      <header className="flex items-center justify-between px-8 py-4 border-b border-slate-800 bg-slate-900/50 backdrop-blur-md">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-emerald-500/10 rounded-lg border border-emerald-500/20">
            <ScanLine className="w-6 h-6 text-emerald-400" />
          </div>
          <h1 className="text-xl font-semibold tracking-tight text-white">Sentinel POS</h1>
        </div>
        <div className="flex items-center gap-4 text-sm text-slate-400">
          <button onClick={() => usePOSStore.getState().toggleCopilot()} className="p-2 bg-blue-100 text-blue-600 rounded-lg font-bold flex items-center gap-2">
            <Bot size={20}/> Ask Copilot
          </button>
          <Link href="/suppliers" className="p-2 text-sm font-semibold text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors flex items-center gap-2">
            <BarChart3 size={20} /> Vendor Intelligence
          </Link>
          <span className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
            Kafka Mesh Online
          </span>
        </div>
      </header>

      <main className="flex h-[calc(100vh-73px)]">
        {/* Left Panel: Scanner & Search */}
        <div className="w-1/2 p-8 border-r border-slate-800 flex flex-col gap-8">
          
          {/* Manual Entry Section */}
          <div className="bg-slate-900/50 p-6 rounded-2xl border border-slate-800 shadow-xl">
            <h2 className="text-lg font-medium text-white mb-4 flex items-center gap-2">
              <Search className="w-5 h-5 text-slate-400" />
              Manual Entry
            </h2>
            <form onSubmit={handleManualAdd} className="relative">
              <input 
                type="text" 
                value={manualInput}
                onChange={(e) => setManualInput(e.target.value)}
                placeholder="Type barcode or medicine name..." 
                className="w-full bg-slate-950 border border-slate-700 rounded-xl py-4 px-5 text-white placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50 transition-all"
              />
              <button type="submit" className="absolute right-3 top-3 bg-slate-800 hover:bg-slate-700 text-white px-4 py-1.5 rounded-lg transition-colors">
                Add
              </button>
            </form>
          </div>

          {/* Sleek Global Scanner Status */}
          <div className="mt-6 bg-blue-50/5 dark:bg-blue-900/10 border border-blue-100 dark:border-blue-900/30 rounded-xl p-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-blue-100 dark:bg-blue-900/50 rounded-lg">
                <ScanLine className="w-5 h-5 text-blue-600 dark:text-blue-400" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-gray-900 dark:text-white">Hardware Scanner Active</h3>
                <p className="text-xs text-gray-500 dark:text-gray-400">Global listener enabled. Scan any barcode instantly.</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="relative flex h-3 w-3">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-3 w-3 bg-green-500"></span>
              </span>
              <span className="text-xs font-bold text-green-600 dark:text-green-400 uppercase tracking-wider">Ready</span>
            </div>
          </div>
        </div>

        {/* Right Panel: The Cart */}
        <div className="w-1/2 bg-slate-900/30 flex flex-col relative">
          <div className="p-8 flex-1 overflow-y-auto">
            <h2 className="text-2xl font-semibold text-white mb-6 flex items-center gap-3">
              <ShoppingCart className="w-6 h-6 text-emerald-400" />
              Current Order
            </h2>

            {/* Cart Items with Framer Motion for smooth entry/exit */}
            <div className="flex flex-col gap-3">
              <AnimatePresence>
                {cart.length === 0 && (
                  <motion.p 
                    initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
                    className="text-slate-500 text-center py-10"
                  >
                    Cart is empty. Scan an item to begin.
                  </motion.p>
                )}
                {cart.map((item) => (
                  <motion.div 
                    key={item.batch_id}
                    initial={{ opacity: 0, y: 20, scale: 0.95 }}
                    animate={{ opacity: 1, y: 0, scale: 1 }}
                    exit={{ opacity: 0, x: -50, scale: 0.95 }}
                    transition={{ duration: 0.2 }}
                    className="flex items-center justify-between bg-slate-800/50 p-4 rounded-xl border border-slate-700/50 hover:border-slate-600 transition-colors"
                  >
                    <div>
                      <h3 className="text-white font-medium">{item.name}</h3>
                      <p className="text-sm text-slate-400">Batch: {item.batch_id}</p>
                    </div>
                    <div className="flex items-center gap-6">
                      <span className="text-lg font-semibold text-emerald-400">
                        ₹{(item.price * item.quantity).toFixed(2)}
                      </span>
                      <div className="flex items-center gap-3 bg-slate-950 px-3 py-1 rounded-lg border border-slate-800">
                        <span className="text-slate-300">Qty:</span>
                        <span className="text-white font-medium">{item.quantity}</span>
                      </div>
                      <button 
                        onClick={() => removeItem(item.batch_id)}
                        className="p-2 text-slate-500 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-colors"
                      >
                        <Trash2 className="w-5 h-5" />
                      </button>
                    </div>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          </div>

          {/* Checkout Footer */}
          <div className="p-8 bg-slate-900 border-t border-slate-800">
            <div className="flex items-center justify-between mb-6">
              <span className="text-slate-400 text-lg">Total Amount</span>
              <span className="text-4xl font-bold text-white">₹{getTotal().toFixed(2)}</span>
            </div>
            <button 
              onClick={handleCheckout}
              disabled={cart.length === 0 || isProcessing}
              className="w-full bg-emerald-500 hover:bg-emerald-400 disabled:bg-slate-800 disabled:text-slate-500 text-slate-950 font-bold text-lg py-5 rounded-xl flex items-center justify-center gap-3 transition-all shadow-[0_0_40px_-10px_rgba(16,185,129,0.5)] disabled:shadow-none"
            >
              {isProcessing ? (
                <span className="animate-pulse">Processing via Kafka...</span>
              ) : (
                <>
                  <CreditCard className="w-6 h-6" />
                  Complete Transaction
                </>
              )}
            </button>
          </div>
        </div>
      </main>
      <CopilotPanel />
    </div>
  );
}
