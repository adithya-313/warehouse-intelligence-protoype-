"use client";

import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { AlertTriangle, ShoppingCart, CheckCircle2 } from "lucide-react";
import { api, DiseaseWaveAlert } from "@/services/api";
import { cn } from "@/lib/utils";

export function PreemptiveWarningBanner() {
  const [alerts, setAlerts] = useState<DiseaseWaveAlert[]>([]);
  const [isOrdering, setIsOrdering] = useState(false);
  const [orderSuccess, setOrderSuccess] = useState<string | null>(null);

  useEffect(() => {
    // Fetch alerts on mount
    api.fetchWaveAlerts().then(setAlerts).catch(console.error);
  }, []);

  const handleOneClickPO = async (alert: DiseaseWaveAlert) => {
    setIsOrdering(true);
    try {
      const res = await api.createAutoPO(alert.sku_id, alert.recommended_supplier_id, alert.expected_volume);
      setOrderSuccess(`PO #${res.po_id} routed successfully!`);
      // Remove alert after success
      setTimeout(() => setAlerts((prev) => prev.filter((a) => a.sku_id !== alert.sku_id)), 3000);
    } catch (error) {
      console.error(error);
    } finally {
      setIsOrdering(false);
    }
  };

  if (alerts.length === 0) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="mb-6 rounded-[2rem] p-[1px] bg-gradient-to-br from-rose-400/60 via-orange-300/60 to-amber-200/60 shadow-[0_16px_32px_rgba(225,29,72,0.15)]"
      >
        <div className="bg-white/80 backdrop-blur-3xl rounded-[calc(2rem-1px)] p-6 flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-rose-100 text-rose-600 rounded-full">
              <AlertTriangle className="w-6 h-6" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-800 flex items-center gap-2">
                Epidemiological Wave Detected
                <span className="text-xs font-semibold px-2 py-1 bg-rose-100 text-rose-700 rounded-full">
                  {(alerts[0].probability_score * 100).toFixed(0)}% Probability
                </span>
              </h3>
              <p className="text-sm text-slate-600 mt-1">{alerts[0].warning_message}</p>
              <p className="text-sm font-medium text-slate-700 mt-1">
                Recommended Action: Procure {alerts[0].expected_volume} units of {alerts[0].sku_name}.
              </p>
            </div>
          </div>

          <button
            onClick={() => handleOneClickPO(alerts[0])}
            disabled={isOrdering || !!orderSuccess}
            className={cn(
              "flex items-center gap-2 px-6 py-3 rounded-xl font-semibold text-white transition-all shadow-md",
              orderSuccess 
                ? "bg-emerald-500 hover:bg-emerald-600" 
                : "bg-gradient-to-r from-rose-500 to-orange-500 hover:from-rose-600 hover:to-orange-600 hover:shadow-lg hover:-translate-y-0.5",
              isOrdering && "opacity-70 cursor-not-allowed"
            )}
          >
            {orderSuccess ? (
              <>
                <CheckCircle2 className="w-5 h-5" />
                {orderSuccess}
              </>
            ) : (
              <>
                <ShoppingCart className="w-5 h-5" />
                {isOrdering ? "Routing PO..." : "1-Click Approve PO"}
              </>
            )}
          </button>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
