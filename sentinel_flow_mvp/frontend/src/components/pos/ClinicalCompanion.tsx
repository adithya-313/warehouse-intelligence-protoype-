"use client";

import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ScanLine, Plus, Zap, TrendingUp } from 'lucide-react';
import { CrossSellItem, GenericAlternative } from '@/services/api';

interface ClinicalCompanionProps {
  loading: boolean;
  crossSells: CrossSellItem[];
  genericAlts: GenericAlternative[];
  onAddItem: (item: { batch_id: string; sku_id: string; name: string; price: number }) => void;
}

function CrossSellCard({ item, onAdd }: { item: CrossSellItem; onAdd: () => void }) {
  const confidencePct = Math.round(item.confidence_score * 100);
  const badgeColor = confidencePct >= 85 ? 'bg-emerald-50 text-emerald-700 border-emerald-200' :
    confidencePct >= 70 ? 'bg-amber-50 text-amber-700 border-amber-200' :
    'bg-slate-50 text-slate-600 border-slate-200';

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2 }}
      className="flex-shrink-0 w-52 bg-white/70 backdrop-blur-xl rounded-2xl border border-slate-100/60 shadow-sm p-4 flex flex-col gap-3 hover:shadow-md transition-shadow"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-bold text-slate-800 text-sm truncate">{item.recommended_sku}</div>
          <div className="text-[10px] text-slate-400 mt-0.5">Clinical Cross-Sell</div>
        </div>
        <div className={`flex items-center gap-1 px-2 py-1 rounded-lg border text-[10px] font-semibold whitespace-nowrap ${badgeColor}`}>
          <Zap size={10} />
          {confidencePct}% Match
        </div>
      </div>
      <button
        onClick={onAdd}
        className="flex items-center justify-center gap-1.5 w-full py-2 rounded-xl bg-blue-50 hover:bg-blue-100 text-blue-700 text-xs font-semibold transition-colors border border-blue-200/50"
      >
        <Plus size={14} />
        Add to Cart
      </button>
    </motion.div>
  );
}

function GenericCard({ item, onAdd }: { item: GenericAlternative; onAdd: () => void }) {
  const savings = item.mrp - item.cost;
  const savingsPct = item.cost > 0 ? Math.round((savings / item.mrp) * 100) : 0;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2, delay: 0.05 }}
      className="flex-shrink-0 w-52 bg-white/70 backdrop-blur-xl rounded-2xl border border-slate-100/60 shadow-sm p-4 flex flex-col gap-3 hover:shadow-md transition-shadow"
    >
      <div className="min-w-0">
        <div className="font-bold text-slate-800 text-sm truncate">{item.sku_id}</div>
        <div className="text-[10px] text-slate-400 mt-0.5">Batch: {item.batch_id}</div>
      </div>
      <div className="flex items-center justify-between">
        <span className="font-semibold text-slate-900 text-sm">₹{item.mrp.toFixed(2)}</span>
        <div className="flex items-center gap-1 px-2 py-1 bg-emerald-50 border border-emerald-200 rounded-lg text-[10px] font-semibold text-emerald-700">
          <TrendingUp size={10} />
          {savingsPct}% Margin
        </div>
      </div>
      <button
        onClick={onAdd}
        className="flex items-center justify-center gap-1.5 w-full py-2 rounded-xl bg-emerald-50 hover:bg-emerald-100 text-emerald-700 text-xs font-semibold transition-colors border border-emerald-200/50"
      >
        <Plus size={14} />
        Add Generic
      </button>
    </motion.div>
  );
}

export default function ClinicalCompanion({ loading, crossSells, genericAlts, onAddItem }: ClinicalCompanionProps) {
  const hasData = crossSells.length > 0 || genericAlts.length > 0;

  return (
    <div className="flex-1 rounded-[2rem] p-[1px] bg-gradient-to-br from-white/40 to-white/10">
      <div className="h-full w-full bg-white/40 backdrop-blur-xl rounded-[calc(2rem-1px)] flex flex-col overflow-hidden">
        <AnimatePresence mode="wait">
          {loading ? (
            <motion.div
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="flex-1 flex items-center justify-center"
            >
              <div className="flex items-center gap-3 text-slate-400">
                <div className="w-5 h-5 border-2 border-blue-200 border-t-blue-500 rounded-full animate-spin" />
                <span className="text-sm font-medium">Loading recommendations...</span>
              </div>
            </motion.div>
          ) : !hasData ? (
            <motion.div
              key="empty"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="flex-1 flex flex-col items-center justify-center text-center p-10"
            >
              <div className="w-20 h-20 bg-white/60 rounded-3xl flex items-center justify-center mb-6 shadow-sm border border-white">
                <ScanLine size={32} className="text-slate-300" />
              </div>
              <h3 className="text-xl font-semibold text-slate-700 mb-2">Ready for next patient</h3>
              <p className="text-slate-400 max-w-sm">The system is listening. Scan a product to instantly add it to the active transaction.</p>
            </motion.div>
          ) : (
            <motion.div
              key="recommendations"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="flex-1 flex flex-col gap-6 p-6 overflow-y-auto"
            >
              {crossSells.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <div className="w-6 h-6 bg-blue-100 rounded-lg flex items-center justify-center">
                      <Zap size={12} className="text-blue-600" />
                    </div>
                    <h4 className="text-sm font-bold text-slate-700">Clinical Cross-Sells</h4>
                    <span className="text-[10px] text-slate-400 font-medium ml-auto">Graph Network</span>
                  </div>
                  <div className="flex gap-3 overflow-x-auto pb-2 scrollbar-thin">
                    {crossSells.map((item) => (
                      <CrossSellCard
                        key={item.recommended_sku}
                        item={item}
                        onAdd={() => onAddItem({ batch_id: item.recommended_sku, sku_id: item.recommended_sku, name: item.recommended_sku, price: 0 })}
                      />
                    ))}
                  </div>
                </div>
              )}

              {genericAlts.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <div className="w-6 h-6 bg-emerald-100 rounded-lg flex items-center justify-center">
                      <TrendingUp size={12} className="text-emerald-600" />
                    </div>
                    <h4 className="text-sm font-bold text-slate-700">High-Margin Alternates</h4>
                    <span className="text-[10px] text-slate-400 font-medium ml-auto">Generic Conversion</span>
                  </div>
                  <div className="flex gap-3 overflow-x-auto pb-2 scrollbar-thin">
                    {genericAlts.map((item) => (
                      <GenericCard
                        key={item.batch_id}
                        item={item}
                        onAdd={() => onAddItem({ batch_id: item.batch_id, sku_id: item.sku_id, name: item.sku_id, price: item.mrp })}
                      />
                    ))}
                  </div>
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
