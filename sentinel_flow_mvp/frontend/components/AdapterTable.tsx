'use client';

import { motion } from 'framer-motion';

interface Adapter {
  id: string;
  module_name: string;
  base_model_version: string;
  adapter_weights_path: string | null;
  status: string;
  created_at: string;
}

const statusColors: Record<string, string> = {
  TRAINING: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
  VALIDATING: 'bg-accent-indigo/20 text-accent-indigo border-accent-indigo/30',
  ACTIVE: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  FAILED: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
  ROLLED_BACK: 'bg-white/5 text-white/30 border-white/10',
};

export default function AdapterTable({
  adapters,
  loading,
}: {
  adapters: Adapter[];
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="skeleton h-12 rounded-xl" />
        ))}
      </div>
    );
  }

  if (adapters.length === 0) {
    return (
      <div className="text-center py-8 text-white/20 text-sm">
        No adapters registered yet
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-white/30 text-[11px] uppercase tracking-wider">
            <th className="pb-3 pr-4 font-medium">Module</th>
            <th className="pb-3 pr-4 font-medium">Base Version</th>
            <th className="pb-3 pr-4 font-medium">Status</th>
            <th className="pb-3 pr-4 font-medium">Weights Path</th>
            <th className="pb-3 font-medium">Created</th>
          </tr>
        </thead>
        <tbody>
          {adapters.map((a, i) => (
            <motion.tr
              key={a.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04 }}
              className="border-t border-white/[0.04]"
            >
              <td className="py-3 pr-4 text-white/80 font-medium">
                {a.module_name}
              </td>
              <td className="py-3 pr-4 text-white/40 text-[13px]">
                {a.base_model_version}
              </td>
              <td className="py-3 pr-4">
                <span
                  className={`inline-block px-2.5 py-0.5 rounded-full text-[11px] font-medium border ${
                    statusColors[a.status] || statusColors.FAILED
                  }`}
                >
                  {a.status}
                </span>
              </td>
              <td className="py-3 pr-4 text-white/30 text-[13px] font-mono max-w-[180px] truncate">
                {a.adapter_weights_path || '—'}
              </td>
              <td className="py-3 text-white/30 text-[13px]">
                {new Date(a.created_at).toLocaleDateString()}
              </td>
            </motion.tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
