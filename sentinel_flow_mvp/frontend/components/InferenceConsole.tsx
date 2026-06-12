'use client';

import { useEffect, useState, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Key,
  Eye,
  EyeOff,
  Users,
  Sparkles,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import { api, getApiKey, setApiKey, fetchHardwareCatalog, CatalogItem } from '@/services/api';
import { toast } from 'sonner';
import PremiumLoader from './PremiumLoader';
import ConfidenceChart from './ConfidenceChart';
import ErrorBoundary from './ErrorBoundary';



const MODULES = ['demand_forecast', 'stockout_prediction'];

function formatChartData(
  rawHistorical?: number[],
  rawForecast?: number[]
) {
  if (!rawHistorical || !rawForecast) return [];

  // Sanitize: remove null, undefined, NaN
  let historical = rawHistorical.filter((v) => v != null && !Number.isNaN(v));
  let forecast = rawForecast.filter((v) => v != null && !Number.isNaN(v));

  // Decimate: if length > 1000, keep every Nth item
  if (forecast.length > 1000) {
    const n = Math.ceil(forecast.length / 1000);
    forecast = forecast.filter((_, i) => i % n === 0);
  }
  if (historical.length > 1000) {
    const n = Math.ceil(historical.length / 1000);
    historical = historical.filter((_, i) => i % n === 0);
  }
  if (!historical || !forecast) return [];
  const data = [];

  const histPoints = historical;
  for (let i = 0; i < histPoints.length; i++) {
    data.push({
      day: `D-${histPoints.length - i}`,
      actual: histPoints[i]
    });
  }

  if (histPoints.length > 0 && forecast.length > 0) {
    data.push({
      day: `Today`,
      actual: histPoints[histPoints.length - 1],
      predicted: histPoints[histPoints.length - 1],
      upper: histPoints[histPoints.length - 1],
      lower: histPoints[histPoints.length - 1]
    });
  }

  for (let i = 0; i < forecast.length; i++) {
    data.push({
      day: `D+${i + 1}`,
      predicted: forecast[i],
      upper: forecast[i] * 1.05,
      lower: forecast[i] * 0.95
    });
  }

  return data;
}

export default function InferenceConsole() {
  const [apiKey, setApiKeyState] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [catalog, setCatalog] = useState<CatalogItem[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [supplier, setSupplier] = useState('');
  const [sku, setSku] = useState('');
  const [moduleId, setModuleId] = useState('demand_forecast');
  const [loading, setLoading] = useState(false);
  const [loadingStatus, setLoadingStatus] = useState('Executing Model...');
  const [error, setError] = useState('');
  const [result, setResult] = useState<{
    prediction_value: number;
    confidence_score: number;
    fallback_engaged: boolean;
    model_version: string;
    historical_trajectory?: number[];
    forecast_trajectory?: number[];
  } | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);
  const pollingTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Cleanup effect to prevent memory leaks and dangling async requests when the component unmounts
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
      if (pollingTimeoutRef.current) {
        clearTimeout(pollingTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const data = await fetchHardwareCatalog();
        console.log("REACT STATE - Catalog API response:", JSON.stringify(data));
        setCatalog(data);
        if (data.length > 0) {
          setSupplier(data[0].supplier_id);
          setSku(data[0].skus[0] || '');
          console.log("REACT STATE - Initial supplier set to:", data[0].supplier_id);
        }
      } catch (e) {
        console.error('Failed to fetch catalog from backend:', e);
      } finally {
        setCatalogLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (catalog.length > 0 && supplier) {
      const currentSupplierData = catalog.find(c => c.supplier_id === supplier);
      if (currentSupplierData && currentSupplierData.skus.length > 0) {
        if (!currentSupplierData.skus.includes(sku)) {
          setSku(currentSupplierData.skus[0]);
        }
      } else {
        setSku('');
      }
    }
  }, [supplier, catalog]);

  const handleExecute = async () => {
    setError('');
    setResult(null);
    setApiKey(apiKey);
    setLoading(true);
    setLoadingStatus('AI Engine Queued...');
    
    try {
      // Assign a new AbortController for this execution cycle to allow cancellation
      abortControllerRef.current = new AbortController();

      const initRes = await api.predict({
        module_id: moduleId,
        supplier_id: supplier,
        sku_id: sku,
        route_id: "Taiwan -> Kochi Port",
        compute_budget: 50.0,
      }, abortControllerRef.current.signal);

      const taskId = initRes.task_id;
      
      const pollTask = async (pollCount = 0, transientErrorCount = 0) => {
        // The "Infinite Pending" Kill Switch: Prevent waiting endlessly if backend is stuck
        if (pollCount > 60) {
          const msg = 'Task Timeout: The backend took too long to respond';
          setError(msg);
          toast.error(msg, {
            style: { background: 'rgba(225, 29, 72, 0.1)', border: '1px solid rgba(225, 29, 72, 0.2)', color: '#fda4af' }
          });
          setLoading(false);
          return;
        }

        try {
          const res = await api.getTaskStatus(taskId, abortControllerRef.current?.signal);
          if (res.status === 'PENDING') {
            setLoadingStatus('AI Engine Processing...');
            pollingTimeoutRef.current = setTimeout(() => pollTask(pollCount + 1, 0), 1000);
          } else if (res.status === 'SUCCESS' && res.result) {
            setResult(res.result);
            toast.success('Inference pipeline execution successful.');
            setLoading(false);
          } else {
            throw new Error(res.error || 'Prediction failed');
          }
        } catch (e: unknown) {
          const msg = e instanceof Error ? e.message : 'Prediction failed';
          
          if (msg.includes('Aborted')) return; // Exit silently if unmounted

          // Transient Degradation Backoff Logic
          // Do not immediately fail. If under 3 retries, calculate exponential backoff.
          if (transientErrorCount < 3) {
            const backoffMs = Math.min(1000 * (2 ** transientErrorCount), 5000);
            console.warn(`Backend unreachable, applying backoff of ${backoffMs}ms...`);
            pollingTimeoutRef.current = setTimeout(() => pollTask(pollCount + 1, transientErrorCount + 1), backoffMs);
            return;
          }

          setError(msg);
          toast.error(msg, {
            style: {
              background: 'rgba(225, 29, 72, 0.1)',
              border: '1px solid rgba(225, 29, 72, 0.2)',
              color: '#fda4af',
            }
          });
          setLoading(false);
        }
      };
      
      pollingTimeoutRef.current = setTimeout(() => pollTask(0, 0), 1000);
      
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Prediction failed';
      setError(msg);
      toast.error(msg, {
        style: {
          background: 'rgba(225, 29, 72, 0.1)',
          border: '1px solid rgba(225, 29, 72, 0.2)',
          color: '#fda4af',
        }
      });
      setLoading(false);
    }
  };

  console.log("RAW CHART INJECTION:", {
    hist: result?.historical_trajectory,
    fore: result?.forecast_trajectory
  });

  const displayUnits = result?.forecast_trajectory && result.forecast_trajectory.length > 0
    ? Math.round(result.forecast_trajectory[result.forecast_trajectory.length - 1])
    : (result ? Math.round(result.prediction_value) : 0);

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass-card space-y-6"
    >
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-xl bg-accent-indigo/10 border border-accent-indigo/20">
          <Sparkles className="w-4 h-4 text-accent-indigo" />
        </div>
        <div>
          <h2 className="text-base font-semibold text-white/90">
            Executive Command Suite
          </h2>
          <p className="text-xs text-white/30 mt-0.5">
            Inference Console
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-2">
          <label className="text-[11px] font-medium text-white/40 uppercase tracking-wider">
            API Key
          </label>
          <div className="relative">
            <Key className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/20" />
            <input
              type={showKey ? 'text' : 'password'}
              value={apiKey}
              onChange={(e) => setApiKeyState(e.target.value)}
              placeholder="sk-..."
              className="input-glass pl-10 pr-10"
            />
            <button
              onClick={() => setShowKey(!showKey)}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-white/20 hover:text-white/40 transition-colors"
            >
              {showKey ? (
                <EyeOff className="w-4 h-4" />
              ) : (
                <Eye className="w-4 h-4" />
              )}
            </button>
          </div>
        </div>

        {/* Contextual Dropdowns */}
        <div className="space-y-2">
          <label className="text-[11px] font-medium text-white/40 uppercase tracking-wider">
            Supplier
          </label>
          <div className="relative">
            <Users className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/20" />
            <select
              value={supplier}
              onChange={(e) => setSupplier(e.target.value)}
              className="input-glass pl-10 appearance-none bg-slate-800 text-slate-100"
            >
              <option value="" className="bg-slate-800 text-slate-100">
                {catalogLoading ? 'Loading catalog...' : 'Select supplier...'}
              </option>
              {catalog.map((c) => (
                <option key={c.supplier_id} value={c.supplier_id} className="bg-slate-800 text-slate-100">
                  {c.supplier_id}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="space-y-2">
          <label className="text-[11px] font-medium text-white/40 uppercase tracking-wider">
            SKU (Optional)
          </label>
          <div className="relative">
            <Sparkles className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/20" />
            <select
              value={sku}
              onChange={(e) => setSku(e.target.value)}
              className="input-glass pl-10 appearance-none bg-slate-800 text-slate-100"
            >
              <option value="" className="bg-slate-800 text-slate-100">Select SKU...</option>
              {catalog.find(c => c.supplier_id === supplier)?.skus.map((s) => (
                <option key={s} value={s} className="bg-slate-800 text-slate-100">{s}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-[11px] font-medium text-white/40 uppercase tracking-wider">
          Module
        </label>
        <div className="flex flex-wrap gap-2">
          {MODULES.map((m) => (
            <button
              key={m}
              onClick={() => setModuleId(m)}
              className={`px-4 py-2 rounded-xl text-sm font-medium border transition-all duration-200 ${moduleId === m
                  ? 'bg-accent-indigo/15 border-accent-indigo/30 text-accent-indigo'
                  : 'bg-white/[0.03] border-white/[0.06] text-white/50 hover:bg-white/[0.06]'
                }`}
            >
              {m.replace(/_/g, ' ')}
            </button>
          ))}
        </div>
      </div>

      <button
        onClick={handleExecute}
        disabled={loading || !apiKey || !supplier}
        className="btn-primary w-full flex items-center justify-center gap-2"
      >
        {loading ? (
          <span className="flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            {loadingStatus}
          </span>
        ) : (
          <>
            <Sparkles className="w-4 h-4" />
            Execute Forecast Engine
          </>
        )}
      </button>

      <AnimatePresence mode="wait">
        {loading && <PremiumLoader label="Running inference pipeline..." />}

        {error && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="flex items-start gap-3 p-4 rounded-xl bg-rose-500/10 border border-rose-500/20"
          >
            <AlertCircle className="w-4 h-4 text-rose-400 mt-0.5 shrink-0" />
            <div>
              <p className="text-sm text-rose-300 font-medium">Inference Failed</p>
              <p className="text-xs text-rose-300/60 mt-0.5">{error}</p>
            </div>
          </motion.div>
        )}

        {!result && !loading && !error && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col items-center justify-center py-12 px-4 border border-white/[0.06] rounded-xl bg-white/[0.02]"
          >
            <Sparkles className="w-8 h-8 text-white/20 mb-3" />
            <p className="text-sm font-medium text-white/50">Awaiting Data</p>
            <p className="text-xs text-white/30 mt-1 text-center">Execute the forecast engine to generate an intelligence trajectory.</p>
          </motion.div>
        )}

        {result && !loading && (
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="space-y-4"
          >
            <div className="grid grid-cols-3 gap-3">
              <div className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                <div className="text-[11px] text-white/30 uppercase tracking-wider">
                  Forecast Demand
                </div>
                <div className="text-lg font-semibold text-accent-cyan mt-1">
                  {`${displayUnits.toLocaleString()} Units`}
                </div>
              </div>
              <div className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                <div className="text-[11px] text-white/30 uppercase tracking-wider">Confidence</div>
                <div className="text-lg font-semibold text-accent-indigo mt-1">
                  {(result.confidence_score * 100).toFixed(0)}%
                </div>
              </div>
              <div className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                <div className="text-[11px] text-white/30 uppercase tracking-wider">Model</div>
                <div className="text-sm font-medium text-white/70 mt-1 truncate">
                  {result.model_version}
                </div>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] text-white/30 uppercase tracking-wider">
                  Forecast Trajectory
                </span>
                {result.fallback_engaged && (
                  <span className="text-[10px] text-amber-400/70 font-medium">
                    Fallback engaged
                  </span>
                )}
              </div>
              <ErrorBoundary>
                <ConfidenceChart data={formatChartData(result.historical_trajectory, result.forecast_trajectory)} />
              </ErrorBoundary>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
