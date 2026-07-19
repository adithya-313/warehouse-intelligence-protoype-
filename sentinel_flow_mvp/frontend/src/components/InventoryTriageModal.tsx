"use client";

// [STORY: THE KINETIC TRIAGE MASTERPIECE]
// Chapter 3: The Glass Illusion
// We are abandoning the dark, brutalist modal. This new UI feels like physical, frosted glass
// hovering over the POS. We use Framer Motion's spring physics to make it feel alive,
// and a client-side search bar so pharmacists can find drugs instantly without network lag.

import React, { useEffect, useState } from 'react';
import { api } from '../services/api';
import { X, AlertOctagon, AlertTriangle, CheckCircle, Search, Package, TrendingDown } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

interface InventoryTriageModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const InventoryTriageModal: React.FC<InventoryTriageModalProps> = ({ isOpen, onClose }) => {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");

  // Scene 1: Fetching the Intelligence
  useEffect(() => {
    if (!isOpen) return;
    const fetchTriage = async () => {
      setLoading(true);
      try {
        const result = await api.get('/api/v1/inventory/triage');
        setData(result);
      } catch (error) {
        console.error("Failed to load triage data", error);
      } finally {
        setLoading(false);
      }
    };
    fetchTriage();

    const handleKeyDown = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  // Scene 2: Zero-Latency Search Filter
  // We filter the already-aggregated data in memory. This is instant.
  const filteredItems = data?.items?.filter((item: any) =>
    item.sku_id.toLowerCase().includes(searchQuery.toLowerCase())
  ) || [];

  // Scene 3: The Optimized Physics Engine
  // Tuned for zero-jerk, buttery smooth entry/exit.
  // Lower stiffness + higher damping = Apple-grade spatial elasticity.
  const backdropVariants = {
    hidden: { opacity: 0 },
    visible: { opacity: 1, transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] } },
    exit: { opacity: 0, transition: { duration: 0.3, ease: [0.16, 1, 0.3, 1] } },
  };

  const modalVariants = {
    hidden: { opacity: 0, scale: 0.96, y: 15 },
    visible: {
      opacity: 1,
      scale: 1,
      y: 0,
      transition: { type: "spring", damping: 30, stiffness: 250, mass: 0.8 },
    },
    exit: {
      opacity: 0,
      scale: 0.96,
      y: 10,
      transition: { duration: 0.2, ease: "easeOut" },
    },
  };

  const listVariants = {
    hidden: { opacity: 0 },
    visible: { opacity: 1, transition: { staggerChildren: 0.04, delayChildren: 0.1 } },
  };

  const itemVariants = {
    hidden: { opacity: 0, y: 10 },
    visible: { opacity: 1, y: 0, transition: { type: "spring", damping: 25, stiffness: 300 } },
  };

  return (
    <AnimatePresence mode="wait">
      {isOpen && (
        <motion.div
          key="triage-backdrop"
          variants={backdropVariants}
          initial="hidden"
          animate="visible"
          exit="exit"
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/10 backdrop-blur-md p-4 sm:p-8 transform-gpu will-change-transform"
        >
          {/* The Glassmorphic Modal Body — Hardware Accelerated */}
          <motion.div
            key="triage-modal"
            variants={modalVariants}
            className="w-full max-w-5xl h-[85vh] flex flex-col rounded-[2rem] shadow-2xl overflow-hidden bg-white/70 backdrop-blur-2xl border border-white/80 transform-gpu will-change-transform"
          >

            {/* Header & Search Section */}
            <div className="flex flex-col gap-4 p-6 border-b border-gray-200/50 bg-white/40">
              <div className="flex justify-between items-center">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-gradient-to-br from-blue-100 to-rose-100 rounded-xl border border-white shadow-sm">
                    <Package className="text-rose-500" size={24} />
                  </div>
                  <h2 className="text-2xl font-semibold text-slate-800 tracking-tight">
                    Inventory Intelligence
                  </h2>
                </div>
                <button
                  onClick={onClose}
                  className="p-2 rounded-full text-slate-400 hover:text-slate-700 hover:bg-black/5 transition-all active:scale-95"
                >
                  <X size={24} />
                </button>
              </div>

              {/* Frosted Search Input */}
              <div className="relative group">
                <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-rose-500 transition-colors" size={20} />
                <input
                  type="text"
                  placeholder="Search inventory by SKU..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-12 pr-4 py-3 bg-white/50 border border-white/60 rounded-xl text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-rose-200/50 shadow-sm backdrop-blur-md transition-all"
                />
              </div>
            </div>

            {/* Main Content Area */}
            <div className="flex-1 overflow-y-auto p-6 space-y-8 no-scrollbar transform-gpu">
              {loading ? (
                <div className="space-y-4 animate-pulse">
                   <div className="h-24 bg-gradient-to-r from-gray-100 via-white/80 to-gray-100 rounded-2xl w-full border border-white/50"></div>
                   <div className="h-16 bg-gradient-to-r from-gray-100 via-white/80 to-gray-100 rounded-xl w-full border border-white/50 mt-8"></div>
                   <div className="h-16 bg-gradient-to-r from-gray-100 via-white/80 to-gray-100 rounded-xl w-full border border-white/50"></div>
                </div>
              ) : (
                <>
                  {/* Financial Telemetry Banner */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="bg-white/50 p-5 rounded-2xl border border-white shadow-sm flex flex-col justify-between hover:shadow-md hover:-translate-y-0.5 transition-all duration-300 transform-gpu">
                      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Total Asset Value</p>
                      <p className="text-3xl font-bold tracking-tight text-slate-800">₹{data?.metrics?.total_value_inr?.toLocaleString()}</p>
                    </div>

                    <div className="relative bg-rose-50/80 p-5 rounded-2xl border border-rose-200/50 shadow-sm flex flex-col justify-between hover:shadow-md hover:-translate-y-0.5 transition-all duration-300 overflow-hidden transform-gpu">
                      <div className="absolute -right-4 -top-4 opacity-10"><TrendingDown size={100} className="text-rose-500"/></div>
                      <p className="text-xs font-semibold uppercase tracking-wider text-rose-600 mb-2 flex items-center gap-1"><AlertTriangle size={14}/> Capital at Risk ({"<"} 30d)</p>
                      <p className="text-3xl font-bold tracking-tight text-rose-700">₹{data?.metrics?.capital_at_risk_inr?.toLocaleString()}</p>
                    </div>

                    <div className="bg-white/50 p-5 rounded-2xl border border-white shadow-sm flex flex-col justify-between hover:shadow-md hover:-translate-y-0.5 transition-all duration-300 transform-gpu">
                      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500 mb-2">Out of Stock SKUs</p>
                      <p className="text-3xl font-bold tracking-tight text-slate-800">{data?.metrics?.out_of_stock_skus}</p>
                    </div>
                  </div>

                  {/* Action Swimlanes */}
                  <motion.div variants={listVariants} initial="hidden" animate="visible" className="space-y-3">
                    {filteredItems.length === 0 ? (
                      <div className="text-center py-12 text-slate-400 font-medium">No medications found matching "{searchQuery}"</div>
                    ) : (
                      filteredItems.map((item: any) => {
                        let Icon = CheckCircle;
                        let color = "text-emerald-500";
                        let bg = "bg-white/60 hover:bg-white/80";
                        let border = "border-white";
                        let badgeBg = "bg-emerald-100 text-emerald-700";

                        if (item.urgency_level === "CRITICAL") {
                          Icon = AlertOctagon; color = "text-rose-500"; bg = "bg-rose-50/50 hover:bg-rose-50"; border = "border-rose-200/60"; badgeBg = "bg-rose-100 text-rose-700";
                        }
                        if (item.urgency_level === "WARNING") {
                          Icon = AlertTriangle; color = "text-amber-500"; bg = "bg-amber-50/50 hover:bg-amber-50"; border = "border-amber-200/60"; badgeBg = "bg-amber-100 text-amber-700";
                        }

                        return (
                          <motion.div
                            key={item.sku_id}
                            variants={itemVariants}
                            className={`group flex items-center justify-between p-4 rounded-xl border ${border} ${bg} shadow-sm backdrop-blur-md transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md cursor-default transform-gpu will-change-transform`}
                          >
                            <div className="flex items-center gap-4">
                              <div className={`p-2 rounded-lg ${badgeBg} shadow-sm group-hover:scale-110 transition-transform duration-300 transform-gpu`}>
                                <Icon size={20} />
                              </div>
                              <div>
                                <p className="text-lg font-bold text-slate-800 tracking-tight">{item.sku_id}</p>
                                <p className="text-sm text-slate-500 font-medium">Closest Expiry: {item.closest_expiry}</p>
                              </div>
                            </div>
                            <div className="text-right">
                              <p className={`text-2xl font-bold tracking-tight ${color}`}>{item.total_stock}</p>
                              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Total Units</p>
                            </div>
                          </motion.div>
                        );
                      })
                    )}
                  </motion.div>
                </>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};
