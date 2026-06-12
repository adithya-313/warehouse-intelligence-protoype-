'use client';

// ------------------------------------------------------------------
// GlobalRiskMatrix — Supply Chain Risk Dashboard
//
// This component fetches live threat data from the backend API and
// renders it across three visual cards: Stockouts, Dead Stock, and
// Anomalies. It handles three distinct states:
//   1. Loading  — shows a spinning loader while the fetch is in flight
//   2. Error    — shows a red error banner if the API call fails
//   3. Success  — renders the risk cards with color-coded severity
// ------------------------------------------------------------------

import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  AlertTriangle,
  PackageX,
  ShieldAlert,
  ChevronRight,
  TrendingDown,
  Loader2,
  XCircle,
} from 'lucide-react';

// Import the typed fetch function and the inferred TypeScript type from our Zod schema.
// RiskDashboardResponse gives us compile-time safety matching the backend Pydantic model.
import { fetchRiskDashboard } from '../src/services/api';
import type { RiskDashboardResponse } from '../src/services/schemas';

// ------------------------------------------------------------------
// Severity Configuration
//
// Maps each severity level to Tailwind utility classes for the card
// backgrounds, borders, dot indicators, and text labels.
// ------------------------------------------------------------------
const severityConfig = {
  critical: {
    border: 'border-red-500/30',
    bg: 'bg-red-900/20',
    dot: 'bg-red-400',
    text: 'text-red-400',
    label: 'Critical',
  },
  warning: {
    border: 'border-amber-500/25',
    bg: 'bg-amber-900/15',
    dot: 'bg-amber-400',
    text: 'text-amber-300',
    label: 'Warning',
  },
  info: {
    border: 'border-sky-500/20',
    bg: 'bg-sky-900/10',
    dot: 'bg-sky-400',
    text: 'text-sky-300',
    label: 'Info',
  },
};

// ------------------------------------------------------------------
// RiskCard — sub-component for one risk category
//
// Renders a titled card with a list of risk items. Each item is
// color-coded by severity using the config map above.
// ------------------------------------------------------------------
function RiskCard({
  icon,
  title,
  items,
  accentBorder,
  accentIcon,
}: {
  icon: React.ReactNode;
  title: string;
  items: RiskDashboardResponse['stockouts'];
  accentBorder: string;
  accentIcon: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      className={`glass-card border-l-[3px] ${accentBorder}`}
    >
      {/* Card header with icon and title */}
      <div className="flex items-center gap-3 mb-4">
        <div className={`p-2 rounded-xl ${accentIcon}`}>
          {icon}
        </div>
        <div>
          <h3 className="text-sm font-semibold text-white/90">{title}</h3>
          <p className="text-[11px] text-white/30">
            {items.length} flagged {items.length === 1 ? 'supplier' : 'suppliers'}
          </p>
        </div>
      </div>

      {/* Risk item list */}
      <div className="space-y-2">
        {items.map((item, i) => {
          // Look up the severity config for this item.
          // If the severity value is unexpected (e.g., backend sends a typo),
          // we safely fall back to "info" so the UI never breaks.
          const cfg = severityConfig[item.severity] || severityConfig.info;

          return (
            <div
              key={i}
              className={`flex items-start gap-3 p-3 rounded-xl ${cfg.bg} border ${cfg.border}`}
            >
              {/* Small colored dot indicating severity */}
              <span className={`mt-1 w-1.5 h-1.5 rounded-full ${cfg.dot} shrink-0`} />

              {/* Main content: supplier name + metric description */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-white/80 truncate">
                    {item.supplier_id}
                  </span>
                  <span className={`text-[10px] font-medium uppercase ${cfg.text} shrink-0`}>
                    {cfg.label}
                  </span>
                </div>
                <p className="text-xs text-white/40 mt-0.5">{item.metric}</p>
              </div>

              {/* Value displayed on the right side */}
              <span className="text-xs font-semibold text-white/60 shrink-0 mt-0.5">
                {item.value}
              </span>
            </div>
          );
        })}
      </div>

      {/* Footer action link */}
      <button className="mt-4 w-full flex items-center justify-center gap-1.5 text-[11px] text-white/20 hover:text-white/40 transition-colors">
        View all flagged suppliers
        <ChevronRight className="w-3 h-3" />
      </button>
    </motion.div>
  );
}

// ------------------------------------------------------------------
// GlobalRiskMatrix — main component
//
// Manages three pieces of state:
//   riskData   — the parsed API response (null until loaded)
//   isLoading  — true while the fetch is in flight
//   error      — holds an error message if the fetch fails
//
// The useEffect runs once on mount (empty deps array) to fetch data.
// ------------------------------------------------------------------
export default function GlobalRiskMatrix() {
  const [riskData, setRiskData] = useState<RiskDashboardResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Trigger the data fetch once when the component mounts.
  // The empty dependency array [] ensures this runs exactly once.
  useEffect(() => {
    let cancelled = false;

    const loadDashboard = async () => {
      try {
        // Call our typed API function which returns a Zod-validated response.
        const data = await fetchRiskDashboard();

        // Only update state if the component is still mounted.
        // This prevents setting state on an unmounted component (React 18 warning).
        if (!cancelled) {
          setRiskData(data);
        }
      } catch (err: unknown) {
        // Catch any network errors, HTTP errors, or Zod validation failures.
        if (!cancelled) {
          const message = err instanceof Error ? err.message : 'An unexpected error occurred.';
          setError(message);
        }
      } finally {
        // Always remove the loading spinner, even on error.
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    };

    loadDashboard();

    // Cleanup function: set the cancelled flag so the async callback
    // does not attempt to set state after unmount.
    return () => {
      cancelled = true;
    };
  }, []);

  // ------------------------------------------------------------------
  // State 1: Loading
  // Displayed while the fetch is in progress.
  // ------------------------------------------------------------------
  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 space-y-4">
        <Loader2 className="w-8 h-8 text-rose-400 animate-spin" />
        <p className="text-sm text-white/50">Loading live risk telemetry...</p>
      </div>
    );
  }

  // ------------------------------------------------------------------
  // State 2: Error
  // Displayed if the fetch threw an error OR if riskData is null
  // (which should not happen, but we guard against it defensively).
  // ------------------------------------------------------------------
  if (error || !riskData) {
    return (
      <div className="flex items-center gap-3 p-4 rounded-xl bg-red-900/20 border border-red-500/20">
        <XCircle className="w-5 h-5 text-red-400 shrink-0" />
        <p className="text-sm text-white/80">
          Error loading risk matrix: {error || 'Data unavailable'}
        </p>
      </div>
    );
  }

  // ------------------------------------------------------------------
  // State 3: Success
  // Render the three-column risk grid with live data.
  // Each column gets its own RiskCard populated from the typed response.
  // ------------------------------------------------------------------
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className="space-y-6"
    >
      {/* Dashboard header */}
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-xl bg-red-900/20 border border-red-500/20">
          <ShieldAlert className="w-4 h-4 text-red-400" />
        </div>
        <div>
          <h2 className="text-base font-semibold text-white/90">
            Global Risk Matrix
          </h2>
          <p className="text-xs text-white/30 mt-0.5">
            Operational threat overlay &bull; auto-refreshed
          </p>
        </div>
      </div>

      {/* Three-column risk card grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <RiskCard
          icon={<PackageX className="w-4 h-4 text-red-400" />}
          title="Impending Stockouts"
          items={riskData.stockouts}
          accentBorder="border-l-red-500/40"
          accentIcon="bg-red-900/20 border border-red-500/20"
        />
        <RiskCard
          icon={<TrendingDown className="w-4 h-4 text-amber-400" />}
          title="Dead Stock Alert"
          items={riskData.dead_stock}
          accentBorder="border-l-amber-500/40"
          accentIcon="bg-amber-900/15 border border-amber-500/20"
        />
        <RiskCard
          icon={<AlertTriangle className="w-4 h-4 text-amber-400" />}
          title="Anomaly Detection"
          items={riskData.anomalies}
          accentBorder="border-l-amber-500/40"
          accentIcon="bg-amber-900/15 border border-amber-500/20"
        />
      </div>
    </motion.div>
  );
}
