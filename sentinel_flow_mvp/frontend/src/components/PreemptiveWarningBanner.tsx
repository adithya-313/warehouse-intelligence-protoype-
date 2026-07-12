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
  const [orderError, setOrderError] = useState<string | null>(null);

  useEffect(() => {
    // Fetch alerts on mount
    api.fetchWaveAlerts().then(setAlerts).catch(console.error);
  }, []);

  const handleOneClickPO = async (alert: DiseaseWaveAlert) => {
    setIsOrdering(true);
    setOrderError(null); // Reset error state
    try {
      const res = await api.createAutoPO(alert.sku_id, alert.recommended_supplier_id, alert.expected_volume);
      setOrderSuccess(`PO #${res.po_id} routed successfully!`);
      setTimeout(() => setAlerts((prev) => prev.filter((a) => a.sku_id !== alert.sku_id)), 3000);
    } catch (error: any) {
      console.error("PO Creation Failed:", error);
      setOrderError("Failed to route PO. Check backend logs.");
    } finally {
      setIsOrdering(false);
    }
  };

  const visibleAlerts = alerts.filter((a: any) => 
    a.alert_type === 'DISEASE_WAVE' || (a.title && a.title.includes('Wave')) || a.sku_id
  );
  if (visibleAlerts.length === 0) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95 }}
        className="mb-6 rounded-[2rem] p-[1px] bg-gradient-to-br from-rose-400/60 via-orange-300/60 to-amber-200/60 shadow-[0_16px_32px_rgba(225,29,72,0.15)]"
      >
        <div className="max-h-[200px] overflow-y-auto pr-2 space-y-4 custom-scrollbar">
          {alerts.map((alert) => (
            <div key={alert.sku_id} className="bg-white/80 backdrop-blur-3xl rounded-[calc(2rem-1px)] p-6 flex flex-col md:flex-row items-center justify-between gap-4">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-rose-100 text-rose-600 rounded-full">
                  <AlertTriangle className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                    Epidemiological Wave Detected
                    <span className="text-xs font-semibold px-2 py-1 bg-rose-100 text-rose-700 rounded-full">
                      {(alert.probability_score * 100).toFixed(0)}% Probability
                    </span>
                  </h3>
                  <p className="text-sm text-gray-900 mt-1">{alert.warning_message}</p>
                  <p className="text-sm font-medium text-gray-900 mt-1">
                    Recommended Action: Procure {alert.expected_volume} units of {alert.sku_name}.
                  </p>
                </div>
              </div>

              <div className="flex flex-col items-end gap-2">
                <button
                  suppressHydrationWarning={true}
                  onClick={() => handleOneClickPO(alert)}
                  disabled={isOrdering || !!orderSuccess}
                  className={cn(
                    "flex items-center gap-2 px-6 py-3 rounded-xl font-semibold text-white transition-all shadow-md",
                    orderSuccess 
                      ? "bg-emerald-500 hover:bg-emerald-600" 
                      : orderError
                      ? "bg-red-500 hover:bg-red-600"
                      : "bg-gradient-to-r from-rose-500 to-orange-500 hover:from-rose-600 hover:to-orange-600 hover:shadow-lg hover:-translate-y-0.5",
                    isOrdering && "opacity-70 cursor-not-allowed"
                  )}
                >
                  {orderSuccess ? (
                    <><CheckCircle2 className="w-5 h-5" /> {orderSuccess}</>
                  ) : orderError ? (
                    <><AlertTriangle className="w-5 h-5" /> Retry Order</>
                  ) : (
                    <><ShoppingCart className="w-5 h-5" /> {isOrdering ? "Routing PO..." : "1-Click Approve PO"}</>
                  )}
                </button>
                {orderError && <span className="text-xs text-red-500 font-medium">{orderError}</span>}
              </div>
            </div>
          ))}
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
