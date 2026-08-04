"use client";

import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { AlertTriangle, Info } from "lucide-react";
import { api, HealthRiskCurrentResponse, HealthRiskExplainResponse } from "@/services/api";
import { RiskExplainDetails } from "@/components/health-risk/RiskExplainDetails";

// Pill colors per server-computed risk tier — same badge language as the
// degraded-data pill below. Colors are cosmetic; the label itself is server truth.
const TIER_BADGE_STYLES: Record<string, string> = {
  Low: "bg-emerald-50 text-emerald-700 border-emerald-200",
  Moderate: "bg-amber-50 text-amber-700 border-amber-200",
  High: "bg-orange-50 text-orange-700 border-orange-200",
  Severe: "bg-rose-50 text-rose-700 border-rose-200",
};

// ============================================================================
// PreemptiveWarningBanner — real health-risk signals for this pharmacy.
//
// Reads /api/v1/health-risk/current (real scores, not the removed hardcoded
// disease-wave placeholders) and lets the pharmacist drill into /explain/{id}
// for the raw inputs behind each score.
//
// No banner, nothing to see: /current returning an empty score list means no
// scoring data exists yet, so we render null (identical to the old behaviour
// when there were no disease-wave alerts).
// ============================================================================
export function PreemptiveWarningBanner() {
  const [current, setCurrent] = useState<HealthRiskCurrentResponse | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [explainData, setExplainData] = useState<Record<number, HealthRiskExplainResponse>>({});
  const [loadingExplain, setLoadingExplain] = useState(false);

  useEffect(() => {
    api.fetchHealthRiskCurrent().then(setCurrent).catch(console.error);
  }, []);

  const scores = current?.scores ?? [];
  if (scores.length === 0) return null;

  const handleToggleExplain = async (scoreId: number) => {
    if (expandedId === scoreId) {
      setExpandedId(null);
      return;
    }
    setExpandedId(scoreId);
    if (explainData[scoreId]) return; // already fetched once — reuse
    setLoadingExplain(true);
    const data = await api.fetchHealthRiskExplain(scoreId);
    if (data) setExplainData((prev) => ({ ...prev, [scoreId]: data }));
    setLoadingExplain(false);
  };

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95 }}
        data-testid="preemptive-warning-banner"
        className="mb-6 rounded-[2rem] p-[1px] bg-gradient-to-br from-rose-400/60 via-orange-300/60 to-amber-200/60 shadow-[0_16px_32px_rgba(225,29,72,0.15)]"
      >
        <div className="max-h-[260px] overflow-y-auto pr-2 space-y-3 custom-scrollbar">
          <div className="flex items-center gap-3 px-1 pt-1">
            <div className="p-2 bg-rose-100 text-rose-600 rounded-full">
              <AlertTriangle className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-gray-900">Active Health Risk Signals</h2>
              <p className="text-xs text-gray-500">Latest risk scores for this pharmacy&apos;s pincode.</p>
            </div>
          </div>

          {scores.map((score) => {
            const expanded = expandedId === score.id;
            const isDegraded = score.data_status === "degraded";
            return (
              <div key={score.id} className="bg-white/80 backdrop-blur-3xl rounded-[calc(2rem-1px)] p-5">
                <button onClick={() => handleToggleExplain(score.id)} className="w-full text-left">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h3 className="text-base font-bold text-gray-900">{score.disease_category}</h3>
                      <p className="text-sm text-gray-900 mt-1">Confidence {score.confidence}</p>
                      {isDegraded && (
                        <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 border border-amber-200 text-xs font-medium mt-2">
                          <Info size={12} /> based on limited recent data
                        </span>
                      )}
                    </div>
                    <div className="text-right">
                      <span
                        className={`inline-flex items-center px-2.5 py-1 rounded-full border text-xs font-medium mb-1 ${
                          TIER_BADGE_STYLES[score.risk_tier] ?? "bg-slate-50 text-slate-600 border-slate-200"
                        }`}
                      >
                        {score.risk_tier}
                      </span>
                      <p className="text-2xl font-bold text-gray-900">{score.score}</p>
                      <p className="text-xs text-gray-500">risk score / 100</p>
                    </div>
                  </div>
                  <p className="text-xs font-semibold text-rose-600 mt-3 uppercase tracking-wide">
                    {expanded ? "Hide details" : "See details"}
                  </p>
                </button>

                {expanded && (
                  <div className="border-t border-slate-100 pt-4 space-y-3">
                    <RiskExplainDetails
                      isLoading={loadingExplain}
                      factors={explainData[score.id]?.contributing_factors}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </motion.div>
    </AnimatePresence>
  );
}