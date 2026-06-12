'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { BrainCircuit, Shield, Radar } from 'lucide-react';
import InferenceConsole from '../../components/InferenceConsole';
import TelemetryEngine from '../../components/TelemetryEngine';
import GlobalRiskMatrix from '../../components/GlobalRiskMatrix';

type View = 'inference' | 'risk';

export default function Home() {
  const [view, setView] = useState<View>('inference');

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <motion.header
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center justify-between mb-8"
      >
        <div className="flex items-center gap-4">
          <div className="p-2.5 rounded-2xl bg-gradient-to-br from-accent-indigo/20 to-accent-cyan/10 border border-accent-indigo/20 shadow-lg shadow-accent-indigo/5">
            <BrainCircuit className="w-6 h-6 text-accent-indigo" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-white tracking-tight">
              Sentinel-Flow
            </h1>
            <p className="text-xs text-white/30 mt-0.5">
              LoRA Orchestration &middot; Supply Chain Intelligence
            </p>
          </div>
        </div>

        <nav className="flex gap-1 p-1 rounded-2xl bg-white/[0.03] border border-white/[0.06]">
          <button
            onClick={() => setView('inference')}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200 ${
              view === 'inference'
                ? 'bg-accent-indigo/15 text-accent-indigo shadow-sm'
                : 'text-white/40 hover:text-white/60'
            }`}
          >
            <Radar className="w-4 h-4" />
            Inference Console
          </button>
          <button
            onClick={() => setView('risk')}
            className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all duration-200 ${
              view === 'risk'
                ? 'bg-rose-500/15 text-rose-400 shadow-sm'
                : 'text-white/40 hover:text-white/60'
            }`}
          >
            <Shield className="w-4 h-4" />
            Risk Dashboard
          </button>
        </nav>
      </motion.header>

      <AnimatePresence mode="wait">
        {view === 'inference' ? (
          <motion.div
            key="inference"
            initial={{ opacity: 0, x: -12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 12 }}
            className="grid grid-cols-1 gap-8"
          >
            <InferenceConsole />
            <TelemetryEngine />
          </motion.div>
        ) : (
          <motion.div
            key="risk"
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
          >
            <GlobalRiskMatrix />
          </motion.div>
        )}
      </AnimatePresence>

      <footer className="mt-12 text-center text-[11px] text-white/10 tracking-wider uppercase">
        Sentinel-Flow v0.1.0 &bull; Enterprise Intelligence Platform
      </footer>
    </main>
  );
}
