"use client";

import React, { useState, useEffect, useRef } from 'react';
import Link from 'next/link';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, Bot, Settings, BarChart3, ShoppingBag, ArrowRight, Barcode, ScanLine, CheckCircle2, History, Banknote, QrCode, CreditCard } from 'lucide-react';
import { toast, Toaster } from 'sonner';
import { cn } from '@/lib/utils';
import { usePOSStore } from '@/store/posStore';
import CopilotPanel from '@/components/pos/CopilotPanel';
import { PreemptiveWarningBanner } from "@/components/PreemptiveWarningBanner";
import { NotificationBell } from "@/components/NotificationBell";
import { DynamicCapsule } from "@/components/DynamicCapsule";
import { api, PaymentMethod } from '@/services/api';

// Beginner Note: A single-click search result row. Clicking adds 1 unit to the cart.
// Quantity adjustments happen inside the "Current Order" cart sidebar.
function SearchDropdownItem({ item, isHighlighted, onSelect }: { item: any, isHighlighted: boolean, onSelect: (item: any) => void }) {
  // The click handler adds the item with quantity 1 (the Zustand store default).
  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    onSelect(item);
  };

  return (
    <div
      onMouseDown={handleClick}
      className={`flex justify-between items-center p-4 cursor-pointer transition-colors border-b border-slate-50 last:border-none ${
        isHighlighted ? 'bg-blue-50' : 'hover:bg-slate-50'
      }`}
    >
      <div>
        <div className="font-bold text-slate-800 text-sm">{item.name}</div>
        <div className="text-xs text-slate-400">Batch: {item.batch_id} | Location: {item.shelf_location || "UNASSIGNED"}</div>
      </div>
      <div className="flex items-center gap-4 text-right">
        <div>
          <div className="font-semibold text-slate-900 text-sm">₹{item.price.toFixed(2)}</div>
          <div className="text-xs text-emerald-600 font-medium">{item.available_quantity} available</div>
        </div>
      </div>
    </div>
  );
}

export default function POSDashboard() {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  // Dynamic Capsule success state
  const [checkoutSuccess, setCheckoutSuccess] = useState(false);
  const [receiptId, setReceiptId] = useState('');
  // Progressive Disclosure: controls whether we show the "Customer Name" input
  // after a phone number was typed but no match was found.
  const [showNameInput, setShowNameInput] = useState(false);
  // Debounce timer reference so we don't spam the backend on every keystroke
  const phoneLookupTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  const toggleCopilot = usePOSStore((state: any) => state.toggleCopilot);
  const cart = usePOSStore((state: any) => state.cart) || [];
  const addItem = usePOSStore((state: any) => state.addItem);
  const decrementItem = usePOSStore((state: any) => state.decrementItem);
  const removeItem = usePOSStore((state: any) => state.removeItem);
  const clearCart = usePOSStore((state: any) => state.clearCart);
  const isProcessing = usePOSStore((state: any) => state.isProcessing);
  const setProcessing = usePOSStore((state: any) => state.setProcessing);
  const customerPhone = usePOSStore((state: any) => state.customerPhone);
  const customerName = usePOSStore((state: any) => state.customerName);
  const customerId = usePOSStore((state: any) => state.customerId);
  const setCustomer = usePOSStore((state: any) => state.setCustomer);
  
  const totalAmount = cart.reduce((sum: number, item: any) => sum + (item.price * item.quantity), 0);

  // Beginner Note: Adds the selected medication to the global Zustand cart state.
  // Quantity defaults to 1 — adjust inside the cart sidebar.
  const selectItem = (item: any) => {
    addItem({
      batch_id: item.batch_id,
      sku_id: item.sku_id,
      name: item.name,
      price: item.price
    });
    setSearchQuery('');
    setSearchResults([]);
    setHighlightedIndex(-1);
  };

  useEffect(() => {
    if (searchQuery.trim().length < 2) {
      setSearchResults([]);
      return;
    }

    setHighlightedIndex(-1);
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

  // Beginner Note: This handler is called when the pharmacist types in the "Customer Phone" input.
  // When they hit 10 digits, we debounce and check if this patient already exists.
  const handleCustomerPhoneChange = async (phone: string) => {
    setShowNameInput(false);
    setCustomer(phone, '', '');

    if (phone.length === 10) {
      if (phoneLookupTimer.current) clearTimeout(phoneLookupTimer.current);
      phoneLookupTimer.current = setTimeout(async () => {
        const result = await api.lookupPatient(phone);
        if (result) {
          setCustomer(phone, result.name, result.patient_id);
        } else {
          setShowNameInput(true);
        }
      }, 400);
    }
  };

  // Beginner Note: This function handles the entire checkout flow.
  // It locks the UI, submits the cart to the backend, and clears it upon success.
  const executeCheckout = async (method: PaymentMethod) => {
    if (cart.length === 0) return;
    
    setProcessing(true);
    try {
      const response = await api.submitCheckout(cart, customerPhone || undefined, customerName || undefined, method);
      
      // Capture receipt ID (use the actual one or mock a short one if missing)
      const shortId = response.receipt_id ? response.receipt_id.slice(-5) : "805F";
      setReceiptId(`...${shortId}`);
      
      // Trigger Dynamic Capsule animation
      setCheckoutSuccess(true);
      setTimeout(() => setCheckoutSuccess(false), 3500);
      
      // Once successfully saved to the database, we clear the frontend UI cart.
      clearCart();
    } catch (error) {
      const message = error instanceof Error ? error.message : "An unknown error occurred during checkout.";
      toast.error(message, { duration: 5000 });
    } finally {
      setProcessing(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className="relative min-h-screen bg-[#fdfbfb] text-slate-800 selection:bg-blue-100"
    >
      <DynamicCapsule isOpen={checkoutSuccess} receiptId={receiptId} />
      {/* Sonner Toast Renderer — renders above everything else */}
      <Toaster position="top-right" richColors closeButton />

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
            <Link href="/history">
              <motion.button
                whileHover={{ scale: 1.02 }}
                whileTap={{ scale: 0.98 }}
                className="px-5 py-2.5 bg-white/60 hover:bg-white border border-gray-200/50 text-slate-600 rounded-2xl text-sm font-semibold transition-colors flex items-center gap-2 shadow-sm"
              >
                <History size={18} /> History
              </motion.button>
            </Link>
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
                  onBlur={() => {
                    // Delayed dismiss so onMouseDown on a result fires first
                    setTimeout(() => {
                      setSearchResults([]);
                      setHighlightedIndex(-1);
                    }, 200);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'ArrowDown') {
                      e.preventDefault();
                      setHighlightedIndex((prev) =>
                        prev < searchResults.length - 1 ? prev + 1 : 0
                      );
                    } else if (e.key === 'ArrowUp') {
                      e.preventDefault();
                      setHighlightedIndex((prev) =>
                        prev > 0 ? prev - 1 : searchResults.length - 1
                      );
                    } else if (e.key === 'Enter') {
                      e.preventDefault();
                      const idx = highlightedIndex >= 0 ? highlightedIndex : 0;
                      if (searchResults[idx]) {
                        selectItem(searchResults[idx]);
                      }
                    }
                  }}
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
                    {searchResults.map((item, idx) => (
                      <SearchDropdownItem
                        key={item.batch_id}
                        item={item}
                        isHighlighted={idx === highlightedIndex}
                        onSelect={selectItem}
                      />
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
                <h2 className="text-xl font-bold text-slate-800 tracking-tight mb-4">Current Order</h2>
                {/* Progressive Disclosure: Optional Customer Identity */}
                {/* Beginner Note: The pharmacist can optionally type a phone number here.
                    If the patient exists, we show a "Returning Patient" badge and link the
                    receipt to them for automated refill reminders. If not found, we reveal
                    a name field to register them on the fly. */}
                <div className="space-y-2">
                  <input
                    type="tel"
                    placeholder="Customer Phone (Optional)"
                    maxLength={10}
                    value={customerPhone}
                    onChange={(e) => handleCustomerPhoneChange(e.target.value)}
                    className="w-full px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-blue-200 focus:border-blue-300 transition-all"
                  />
                  {customerId && customerName && (
                    <div className="flex items-center gap-2 px-3 py-2 bg-emerald-50 border border-emerald-200 rounded-xl text-sm">
                      <span className="text-emerald-600 font-medium">Returning Patient:</span>
                      <span className="text-emerald-800 font-bold">{customerName}</span>
                    </div>
                  )}
                  {showNameInput && (
                    <input
                      type="text"
                      placeholder="Enter Customer Name"
                      value={customerName}
                      onChange={(e) => setCustomer(customerPhone, e.target.value, '')}
                      className="w-full px-4 py-2.5 bg-white border border-slate-200 rounded-xl text-sm text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-amber-200 focus:border-amber-300 transition-all"
                      autoFocus
                    />
                  )}
                </div>
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
                            
                            {/* Inline Cart Quantity Incrementor */}
                            {/* Beginner Note: This interactive control block lets users adjust quantities without leaving the cart view. */}
                            <div className="flex items-center gap-3 mt-2 bg-slate-50 w-fit p-1 rounded-lg border border-slate-200/50">
                              <button
                                onClick={() => decrementItem(item.batch_id)}
                                className="w-6 h-6 flex items-center justify-center bg-white rounded-md text-slate-600 hover:text-rose-600 shadow-sm transition-colors"
                                title="Decrease Quantity"
                              >
                                -
                              </button>
                              <span className="text-xs font-bold w-4 text-center text-slate-700">
                                {item.quantity}
                              </span>
                              <button
                                onClick={() => addItem({ ...item, quantity: 1 })}
                                className="w-6 h-6 flex items-center justify-center bg-white rounded-md text-slate-600 hover:text-emerald-600 shadow-sm transition-colors"
                                title="Increase Quantity"
                              >
                                +
                              </button>
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
                
                <div className="grid grid-cols-3 gap-3">
                  <button
                    onClick={() => executeCheckout('CASH')}
                    disabled={!mounted || cart.length === 0 || isProcessing}
                    className="flex flex-col items-center justify-center gap-2 py-4 rounded-xl bg-emerald-50 hover:bg-emerald-100 text-emerald-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed border border-emerald-200/50"
                  >
                    <Banknote size={22} />
                    <span className="text-sm font-semibold">Cash</span>
                  </button>
                  <button
                    onClick={() => executeCheckout('UPI')}
                    disabled={!mounted || cart.length === 0 || isProcessing}
                    className="flex flex-col items-center justify-center gap-2 py-4 rounded-xl bg-blue-50 hover:bg-blue-100 text-blue-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed border border-blue-200/50"
                  >
                    <QrCode size={22} />
                    <span className="text-sm font-semibold">UPI</span>
                  </button>
                  <button
                    onClick={() => executeCheckout('CARD')}
                    disabled={!mounted || cart.length === 0 || isProcessing}
                    className="flex flex-col items-center justify-center gap-2 py-4 rounded-xl bg-violet-50 hover:bg-violet-100 text-violet-700 transition-colors disabled:opacity-40 disabled:cursor-not-allowed border border-violet-200/50"
                  >
                    <CreditCard size={22} />
                    <span className="text-sm font-semibold">Card</span>
                  </button>
                </div>
              </div>
            </div>
          </motion.div>

        </div>
      </div>

      {/* COPILOT OVERLAY */}
      <CopilotPanel />
    </motion.div>
  );
}
