'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Database,
  Cpu,
  Network,
  Activity,
  RefreshCw,
} from 'lucide-react';
import MetricCard from './MetricCard';
import AdapterTable from './AdapterTable';
import { api, fetchSystemStats } from '@/services/api';
import { SystemStatsResponse } from '@/services/schemas';

interface Adapter {
  id: string;
  module_name: string;
  base_model_version: string;
  adapter_weights_path: string | null;
  status: string;
  created_at: string;
}

export default function TelemetryEngine() {
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [stats, setStats] = useState<SystemStatsResponse | null>(null);

  const fetchAdapters = async () => {
    setLoading(true);
    try {
      const data = await api.listAdapters();
      setAdapters(data);
      const statsData = await fetchSystemStats();
      setStats(statsData);
    } catch (e) {
      console.error('Failed to fetch telemetry:', e);
    } finally {
      setLoading(false);
      setLastRefresh(new Date());
    }
  };

  useEffect(() => {
    fetchAdapters();
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.15 }}
      className="space-y-6"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
            <Activity className="w-4 h-4 text-emerald-400" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-white/90">
              Core Infrastructure Telemetry
            </h2>
            <p className="text-xs text-white/30 mt-0.5">
              Live system status &amp; adapter registry
            </p>
          </div>
        </div>
        <button
          onClick={fetchAdapters}
          className="p-2 rounded-xl bg-white/[0.04] border border-white/[0.06] text-white/30 hover:text-white/60 hover:bg-white/[0.07] transition-all"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <MetricCard
          icon={<Database className="w-5 h-5" />}
          label="Processed Ledger Records"
          value={stats ? stats.total_telemetry_records.toLocaleString() : "..."}
          sub={stats ? `${stats.total_suppliers} active hardware suppliers` : "Loading..."}
          trend="up"
        />
        <MetricCard
          icon={<Cpu className="w-5 h-5" />}
          label="Active LoRA Adapters"
          value={stats ? stats.active_adapters : 0}
          sub={stats ? `${stats.total_adapters} total registered` : "Loading..."}
          trend={stats && stats.active_adapters > 0 ? 'up' : 'neutral'}
        />
        <MetricCard
          icon={<Network className="w-5 h-5" />}
          label="Neural Backbone"
          value="Active"
          sub={stats ? stats.neural_backbone : "Loading..."}
          trend="up"
        />
      </div>

      <div className="glass-card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-white/70">
            Adapter Registry
          </h3>
          <span className="text-[11px] text-white/20">
            Last refreshed: {lastRefresh.toLocaleTimeString()}
          </span>
        </div>
        <AdapterTable adapters={adapters} loading={loading} />
      </div>
    </motion.div>
  );
}
