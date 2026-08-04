"use client";

// ============================================================================
// HowThisWorksModal — the "How this works" explainer for the Health Risk Radar.
//
// Prose-only, static content. It explains, honestly, where the score comes
// from and what its known limits are:
//
//   Section 1  — the two real data sources (Google Trends + Open-Meteo),
//                as documented in transparent_formula_scorer.py:9-21.
//   Section 2  — what the "based on limited recent data" pill means
//                (data_status === "degraded" in the /current payload).
//                NOTE: deliberately does NOT repeat that exact pill phrase
//                verbatim, so it can never collide with existing assertions.
//   Section 3  — the risk tier caveat from risk_tier.py:28-37: boundaries
//                are a product judgment, not calibrated against outcomes.
//   Section 4  — the honest limitations from docs/health_risk_backtest_2026.md
//                (arbitrary 60/40 weights, monsoon false alarms, tiny sample).
//
// Every claim here is sourced from something already documented in the
// codebase — nothing new is asserted.
//
// The modal follows InventoryTriageModal's isOpen/onClose contract and
// glassmorphic visual language. It unmounts entirely while closed (the
// `isOpen && ...` guard), so none of its copy exists in the DOM until opened.
// ============================================================================

import React, { useEffect } from 'react';
import { X, Radar, TrendingUp, Droplets, ShieldAlert, AlertTriangle } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

interface HowThisWorksModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const backdropVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.3, ease: [0.16, 1, 0.3, 1] } },
  exit: { opacity: 0, transition: { duration: 0.25, ease: [0.16, 1, 0.3, 1] } },
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-bold text-slate-800 tracking-wide">{title}</h3>
      {children}
    </section>
  );
}

export const HowThisWorksModal: React.FC<HowThisWorksModalProps> = ({ isOpen, onClose }) => {
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  return (
    <AnimatePresence mode="wait">
      {isOpen && (
        <motion.div
          key="how-backdrop"
          variants={backdropVariants}
          initial="hidden"
          animate="visible"
          exit="exit"
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/10 backdrop-blur-md p-4 sm:p-8"
        >
          <motion.div
            key="how-modal"
            variants={modalVariants}
            className="w-full max-w-xl max-h-[85vh] flex flex-col rounded-[2rem] shadow-2xl overflow-hidden bg-white/70 backdrop-blur-2xl border border-white/80"
          >
            <div className="flex justify-between items-center p-6 border-b border-gray-200/50 bg-white/40">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-gradient-to-br from-blue-100 to-rose-100 rounded-xl border border-white shadow-sm">
                  <Radar className="text-rose-500" size={22} />
                </div>
                <h2 className="text-xl font-semibold text-slate-800 tracking-tight">
                  How this works
                </h2>
              </div>
              <button
                onClick={onClose}
                aria-label="Close"
                className="p-2 rounded-full text-slate-400 hover:text-slate-700 hover:bg-black/5 transition-all active:scale-95"
              >
                <X size={22} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-6 space-y-6 text-sm leading-relaxed text-slate-600">
              {/* ------------------------------------------------------------------
                  SECTION 1: WHERE THIS COMES FROM
                  Sourced from transparent_formula_scorer.py:9-21 — trend is the
                  leading indicator, weather is the confirming indicator.
                  ------------------------------------------------------------------ */}
              <Section title="Where this comes from">
                <p>This score combines two real signals for your area:</p>
                <ul className="space-y-3">
                  <li className="flex gap-3">
                    <TrendingUp size={16} className="text-indigo-500 shrink-0 mt-0.5" />
                    <p>
                      <span className="font-semibold text-slate-700">Search trends</span> — how
                      often people nearby are searching for symptoms related to this disease.
                      This tends to move first, sometimes a few days before people actually show
                      up at a pharmacy.
                    </p>
                  </li>
                  <li className="flex gap-3">
                    <Droplets size={16} className="text-cyan-500 shrink-0 mt-0.5" />
                    <p>
                      <span className="font-semibold text-slate-700">Weather conditions</span> —
                      humidity and rainfall, which historically track with outbreak conditions
                      in Kerala. This helps confirm whether a spike in searches reflects real
                      risk rather than unrelated concern.
                    </p>
                  </li>
                </ul>
              </Section>

              {/* ------------------------------------------------------------------
                  SECTION 2: WHAT THE DEGRADED-DATA PILL MEANS
                  Mirrors the "based on limited recent data" pill on each card
                  (data_status === "degraded") — but deliberately avoids repeating
                  that exact phrase verbatim, so existing assertions never collide.
                  ------------------------------------------------------------------ */}
              <Section title="What the limited-data note means">
                <p>
                  Sometimes recent runs come back without enough real search or weather data to
                  work with. When that's happened more often than not recently, we say so plainly
                  instead of showing a confident-looking number built on thin evidence.
                </p>
              </Section>

              {/* ------------------------------------------------------------------
                  SECTION 3: ABOUT THE RISK LEVELS
                  Surfaces the honesty caveat from risk_tier.py:28-37 — boundaries
                  are a product decision, uncalibrated against outcome data.
                  ------------------------------------------------------------------ */}
              <Section title="About the risk levels">
                <p>
                  Low, Moderate, High, and Severe are drawn from the raw score using boundaries
                  we set based on judgment, not from validated outbreak outcomes — this formula
                  hasn't been tested against confirmed real-world cases yet. Treat these levels
                  as a rough guide, not a certified risk assessment.
                </p>
              </Section>

              {/* ------------------------------------------------------------------
                  SECTION 4: KNOWN LIMITATIONS
                  From docs/health_risk_backtest_2026.md — "Honest Limitations" and
                  the arbitrary-weight / monsoon-false-alarm / small-sample points.
                  ------------------------------------------------------------------ */}
              <Section title="Known limitations">
                <ul className="space-y-3">
                  <li className="flex gap-3">
                    <AlertTriangle size={16} className="text-amber-500 shrink-0 mt-0.5" />
                    <p>
                      The weighting between search trends and weather (60/40) was chosen
                      deliberately, not learned from data.
                    </p>
                  </li>
                  <li className="flex gap-3">
                    <AlertTriangle size={16} className="text-amber-500 shrink-0 mt-0.5" />
                    <p>
                      Monsoon season will tend to push scores up across the board, which can mean
                      more false alarms during normal seasonal weather, not just real outbreaks.
                    </p>
                  </li>
                  <li className="flex gap-3">
                    <ShieldAlert size={16} className="text-rose-400 shrink-0 mt-0.5" />
                    <p>
                      This is based on a small number of real-world comparisons so far, so treat
                      it as an early-stage signal, not a diagnosis.
                    </p>
                  </li>
                </ul>
              </Section>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};
