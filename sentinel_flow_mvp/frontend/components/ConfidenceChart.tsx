'use client';

import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts';

interface DataPoint {
  day: string;
  actual?: number;
  predicted?: number;
  upper?: number;
  lower?: number;
}

export default function ConfidenceChart({ data }: { data: DataPoint[] }) {
  return (
    <div className="w-full h-[280px]">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <defs>
            <linearGradient id="actualGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#818cf8" stopOpacity={0.5} />
              <stop offset="100%" stopColor="#818cf8" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="confidenceGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#5eead4" stopOpacity={0.25} />
              <stop offset="100%" stopColor="#5eead4" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
          <XAxis
            dataKey="day"
            tick={{ fill: 'rgba(255,255,255,0.2)', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            tick={{ fill: 'rgba(255,255,255,0.2)', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            domain={['auto', 'auto']}
            tickFormatter={(v: number) => Math.round(v).toLocaleString()}
          />
          <Tooltip
            contentStyle={{
              background: 'rgba(6,8,14,0.9)',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 12,
              backdropFilter: 'blur(12px)',
              fontSize: 12,
              color: 'rgba(255,255,255,0.8)',
            }}
            formatter={(value: number, name: string) => [
              `${Math.round(value).toLocaleString()} Units`,
              name.charAt(0).toUpperCase() + name.slice(1),
            ]}
          />
          <Area
            type="monotone"
            dataKey="upper"
            stroke="none"
            fill="rgba(94,234,212,0.06)"
          />
          <Area
            type="monotone"
            dataKey="lower"
            stroke="none"
            fill="rgba(94,234,212,0.06)"
          />
          <Area
            type="monotone"
            dataKey="actual"
            stroke="#818cf8"
            strokeWidth={2}
            fill="url(#actualGrad)"
            dot={false}
          />
          <Area
            type="monotone"
            dataKey="predicted"
            stroke="#5eead4"
            strokeWidth={2}
            strokeDasharray="6 3"
            fill="url(#confidenceGrad)"
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
