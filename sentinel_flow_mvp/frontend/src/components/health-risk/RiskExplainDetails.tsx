"use client";

import { TrendingUp, Droplets, CloudRain, Waves } from "lucide-react";
import type { HealthRiskContributingFactors } from "@/services/api";

// Contributing factors can be null when the underlying weather/trend source was
// unavailable. We render a dash instead of a misleading "0".
export const formatFactor = (value: number | null | undefined, suffix = ""): string =>
  value === null || value === undefined ? "—" : `${value}${suffix}`;

// ============================================================================
// RiskExplainDetails — the raw contributing factors behind one risk score,
// shared by the Health Risk Radar page cards and the POS banner.
//
// Three states:
//   - isLoading:  a pulsing placeholder bar while /explain/{id} is in flight.
//   - factors:    the four real inputs that fed the score, as labeled tiles.
//   - neither:    the explain fetch failed — say so plainly, never fake values.
// ============================================================================
export function RiskExplainDetails({
  isLoading,
  factors,
}: {
  isLoading: boolean;
  factors: HealthRiskContributingFactors | undefined;
}) {
  if (isLoading) {
    return <div className="h-4 bg-slate-200 rounded animate-pulse w-2/3"></div>;
  }

  if (!factors) {
    return <p className="text-sm text-slate-500">Couldn't load the signal breakdown for this score.</p>;
  }

  return (
    <>
      <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
        Raw inputs behind this score
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="flex items-center gap-3 p-3 bg-slate-50 rounded-2xl">
          <TrendingUp size={16} className="text-indigo-500 shrink-0" />
          <div>
            <p className="text-xs text-slate-500">Trend signal</p>
            <p className="font-semibold text-slate-800">{formatFactor(factors.trend_score)} / 100</p>
          </div>
        </div>
        <div className="flex items-center gap-3 p-3 bg-slate-50 rounded-2xl">
          <Droplets size={16} className="text-cyan-500 shrink-0" />
          <div>
            <p className="text-xs text-slate-500">Humidity</p>
            <p className="font-semibold text-slate-800">{formatFactor(factors.humidity_percent, '%')}</p>
          </div>
        </div>
        <div className="flex items-center gap-3 p-3 bg-slate-50 rounded-2xl">
          <CloudRain size={16} className="text-sky-500 shrink-0" />
          <div>
            <p className="text-xs text-slate-500">Rainfall</p>
            <p className="font-semibold text-slate-800">{formatFactor(factors.rain_mm, ' mm')}</p>
          </div>
        </div>
        <div className="flex items-center gap-3 p-3 bg-slate-50 rounded-2xl">
          <Waves size={16} className="text-teal-500 shrink-0" />
          <div>
            <p className="text-xs text-slate-500">Weather anomaly</p>
            <p className="font-semibold text-slate-800">{formatFactor(factors.weather_anomaly)} / 100</p>
          </div>
        </div>
      </div>
    </>
  );
}
