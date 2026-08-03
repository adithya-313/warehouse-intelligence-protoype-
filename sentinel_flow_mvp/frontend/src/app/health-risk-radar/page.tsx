"use client";

import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Radar, Info, TrendingUp, Droplets, CloudRain, Waves } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import {
  api,
  HealthRiskCurrentResponse,
  HealthRiskCurrentScore,
  HealthRiskExplainResponse,
  HealthRiskHistoryResponse,
} from '@/services/api';
import BackButton from '@/components/ui/BackButton';

// Simple fixed palette so each disease gets a distinct (but arbitrary) line color.
// This is purely cosmetic — it is NOT a tier or severity classification.
const CHART_COLORS = ['#6366f1', '#0891b2', '#d97706', '#059669', '#dc2626', '#7c3aed'];

// Show a friendly "Jan 5" style label for a chart x-axis, falling back to the raw
// string if the backend ever sends something we cannot parse.
const formatDate = (iso: string): string => {
  const date = new Date(iso);
  if (isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

// Contributing factors can be null when the underlying weather/trend source was
// unavailable. We render a dash instead of a misleading "0".
const formatFactor = (value: number | null | undefined, suffix = ''): string =>
  value === null || value === undefined ? '—' : `${value}${suffix}`;

// ============================================================================
// DiseaseCard — one disease's current signal. Clicking it deep-links to
// /explain/{id} (using the id field on the /current score) and renders the
// raw contributing factors that fed the score.
// ============================================================================
function DiseaseCard({
  score,
  color,
  selected,
  explainData,
  loadingExplain,
  onToggle,
}: {
  score: HealthRiskCurrentScore;
  color: string;
  selected: boolean;
  explainData: HealthRiskExplainResponse | null;
  loadingExplain: boolean;
  onToggle: () => void;
}) {
  const isDegraded = score.data_status === 'degraded';
  const factors = explainData?.contributing_factors;

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      className="p-[1px] bg-gradient-to-br from-blue-200/50 via-rose-200/50 to-amber-200/50 rounded-[2rem]"
    >
      <div className="bg-white/80 backdrop-blur-3xl rounded-[calc(2rem-1px)] p-6 space-y-4">
        <button onClick={onToggle} className="w-full text-left">
          <div className="flex items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
                <h3 className="font-bold text-slate-900">{score.disease_category}</h3>
              </div>
              <p className="text-sm text-slate-500 mt-1">
                Confidence {score.confidence} · {formatDate(score.computed_at)}
              </p>
            </div>
            <div className="text-right">
              {/* TODO(3.0b): render risk_tier here once the backend adds it —
                  do NOT invent a client-side tier calculation. */}
              <p className="text-3xl font-bold text-slate-900">{score.score}</p>
              <p className="text-xs text-slate-400">risk score / 100</p>
            </div>
          </div>

          {isDegraded && (
            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 border border-amber-200 text-xs font-medium mt-3">
              <Info size={12} /> based on limited recent data
            </span>
          )}

          <p className="text-xs font-semibold text-slate-400 mt-3 uppercase tracking-wide">
            {selected ? 'Hide signal breakdown' : 'View signal breakdown'}
          </p>
        </button>

        {selected && (
          <div className="border-t border-slate-100 pt-4 space-y-3">
            {loadingExplain ? (
              <div className="h-4 bg-slate-200 rounded animate-pulse w-2/3"></div>
            ) : factors ? (
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
            ) : (
              <p className="text-sm text-slate-500">Couldn't load the signal breakdown for this score.</p>
            )}
          </div>
        )}
      </div>
    </motion.div>
  );
}

export default function HealthRiskRadarPage() {
  const [current, setCurrent] = useState<HealthRiskCurrentResponse | null>(null);
  const [history, setHistory] = useState<HealthRiskHistoryResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [explainData, setExplainData] = useState<Record<number, HealthRiskExplainResponse>>({});
  const [loadingExplain, setLoadingExplain] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      // Both fetches resolve even on failure (they return null), so loading
      // always ends and one of the honest states below renders.
      const [cur, hist] = await Promise.all([
        api.fetchHealthRiskCurrent(),
        api.fetchHealthRiskHistory(30),
      ]);
      if (cancelled) return;
      setCurrent(cur);
      setHistory(hist);
      setIsLoading(false);
    };
    load();
    return () => { cancelled = true; };
  }, []);

  const handleToggleExplain = async (scoreId: number) => {
    if (selectedId === scoreId) {
      setSelectedId(null);
      return;
    }
    setSelectedId(scoreId);
    if (explainData[scoreId]) return; // already fetched once — reuse
    setLoadingExplain(true);
    const data = await api.fetchHealthRiskExplain(scoreId);
    if (data) setExplainData((prev) => ({ ...prev, [scoreId]: data }));
    setLoadingExplain(false);
  };

  // Group the 30-day history into one point series per disease, oldest first.
  const historyByDisease: { disease: string; points: { date: number; label: string; score: number }[] }[] = [];
  if (history) {
    const byDisease = new Map<string, { date: number; label: string; score: number }[]>();
    for (const row of history.scores) {
      const date = new Date(row.computed_at);
      const points = byDisease.get(row.disease_category) ?? [];
      points.push({ date: date.getTime() || 0, label: formatDate(row.computed_at), score: row.score });
      byDisease.set(row.disease_category, points);
    }
    for (const [disease, points] of byDisease) {
      points.sort((a, b) => a.date - b.date);
      historyByDisease.push({ disease, points });
    }
  }

  const currentScores: HealthRiskCurrentScore[] = current?.scores ?? [];

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex items-center gap-4">
        <BackButton href="/pos" />
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Health Risk Radar</h1>
          <p className="text-slate-500 mt-1">Disease risk signals for this pharmacy's pincode, updated every 6 hours.</p>
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {[1, 2].map((n) => (
            <div key={n} className="bg-white rounded-3xl shadow-sm border border-slate-200 p-6 space-y-4">
              <div className="h-5 bg-slate-200 rounded animate-pulse w-1/3"></div>
              <div className="h-4 bg-slate-200 rounded animate-pulse w-1/2"></div>
              <div className="h-40 bg-slate-200 rounded-2xl animate-pulse"></div>
            </div>
          ))}
        </div>
      ) : (
        <>
          {/* ================================================================
              SECTION 1: CURRENT SIGNAL BREAKDOWN
              If /current has no diseases at all (realistic today while
              health_risk_enabled is off on the seed tenant), we show an honest
              empty state instead of a blank page or a spinner that never ends.
              ================================================================ */}
          <section>
            <h2 className="text-lg font-bold text-slate-900 mb-4">Current signals</h2>
            {current === null ? (
              <div className="bg-white rounded-3xl shadow-sm border border-slate-200 p-10 text-center text-slate-500">
                <Radar className="mx-auto mb-3 text-slate-300" size={32} />
                <p className="font-semibold text-slate-600">Couldn't load current risk signals</p>
                <p className="text-sm mt-1">The health risk service did not respond. Try again in a moment.</p>
              </div>
            ) : currentScores.length === 0 ? (
              <div className="bg-white rounded-3xl shadow-sm border border-slate-200 p-10 text-center text-slate-500">
                <Radar className="mx-auto mb-3 text-slate-300" size={32} />
                <p className="font-semibold text-slate-600">No current risk signals yet</p>
                <p className="text-sm mt-1">
                  Health risk scoring hasn't produced data for this pharmacy yet. It runs every 6 hours once
                  enabled — check back after the next ingestion cycle.
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {currentScores.map((score, idx) => (
                  <DiseaseCard
                    key={score.id}
                    score={score}
                    color={CHART_COLORS[idx % CHART_COLORS.length]}
                    selected={selectedId === score.id}
                    explainData={explainData[score.id] ?? null}
                    loadingExplain={loadingExplain}
                    onToggle={() => handleToggleExplain(score.id)}
                  />
                ))}
              </div>
            )}
          </section>

          {/* ================================================================
              SECTION 2: TREND GRAPHS (last 30 days)
              One AreaChart per disease, fed by /history?days=30.

              NOTE: The "historical track record" sub-section from the original
              task doc is deliberately deferred — with scoring only recently
              enabled there isn't enough real accumulated history to render it
              honestly. Per the "don't fake history" principle, we wait for real
              data to accumulate before building it.
              ================================================================ */}
          <section>
            <h2 className="text-lg font-bold text-slate-900 mb-4">30-day trend</h2>
            {historyByDisease.length === 0 ? (
              <div className="bg-white rounded-3xl shadow-sm border border-slate-200 p-10 text-center text-slate-500">
                <TrendingUp className="mx-auto mb-3 text-slate-300" size={32} />
                <p className="font-semibold text-slate-600">No historical data yet</p>
                <p className="text-sm mt-1">Check back once scoring has run — trend lines appear as real scores accumulate.</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {historyByDisease.map(({ disease, points }, idx) => (
                  <div key={disease} className="p-[1px] bg-gradient-to-br from-blue-200/50 via-rose-200/50 to-amber-200/50 rounded-[2rem]">
                    <div className="bg-white/80 backdrop-blur-3xl rounded-[calc(2rem-1px)] p-6">
                      <div className="flex items-center justify-between mb-4">
                        <h3 className="font-bold text-slate-900">{disease}</h3>
                        <span className="text-xs text-slate-400">last 30 days</span>
                      </div>
                      <ResponsiveContainer width="100%" height={200}>
                        <AreaChart data={points}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                          <XAxis dataKey="label" tick={{ fontSize: 11, fill: '#94a3b8' }} interval="preserveStartEnd" />
                          <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: '#94a3b8' }} width={32} />
                          <Tooltip />
                          <Area
                            type="monotone"
                            dataKey="score"
                            stroke={CHART_COLORS[idx % CHART_COLORS.length]}
                            fill={CHART_COLORS[idx % CHART_COLORS.length]}
                            fillOpacity={0.12}
                            strokeWidth={2}
                            name="Risk score"
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
