'use client';

import { motion } from 'framer-motion';
import { DivideIcon as LucideIcon } from 'lucide-react';
import { ReactNode } from 'react';

interface MetricCardProps {
  icon: ReactNode;
  label: string;
  value: string | number;
  sub?: string;
  trend?: 'up' | 'down' | 'neutral';
}

export default function MetricCard({
  icon,
  label,
  value,
  sub,
  trend,
}: MetricCardProps) {
  const trendColors: Record<string, string> = {
    up: 'text-emerald-400',
    down: 'text-rose-400',
    neutral: 'text-white/30',
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass-card flex flex-col gap-3"
    >
      <div className="flex items-center justify-between">
        <span className="text-white/30 text-sm">{icon}</span>
        {trend && (
          <span className={`text-[10px] font-medium uppercase tracking-wider ${trendColors[trend]}`}>
            {trend}
          </span>
        )}
      </div>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {sub && <div className="text-[11px] text-white/20 mt-0.5">{sub}</div>}
    </motion.div>
  );
}
