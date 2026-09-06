"use client";

import React, { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ScrollText, ChevronDown, ChevronUp, ChevronLeft, ChevronRight, Filter } from 'lucide-react';
import BackButton from '@/components/ui/BackButton';

// ============================================================================
// Types — mirrors the backend response shape from audit_log_router.py
// ============================================================================
interface AuditLogItem {
  id: number;
  timestamp: string | null;
  tenant_id: string;
  entity_type: string;
  entity_id: string;
  action_type: string;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  extra_metadata: Record<string, unknown> | null;
}

interface AuditLogsResponse {
  items: AuditLogItem[];
  total: number;
  limit: number;
  offset: number;
}

// ============================================================================
// Helpers
// ============================================================================

// Format ISO timestamp to human-readable, e.g. "Sep 5, 2026, 2:14 PM"
function formatTimestamp(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

// Friendly label for entity_type — e.g. "purchase_order" → "Purchase Order"
function entityLabel(type: string): string {
  return type
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

// Color badge for action_type — green for CREATE, amber for UPDATE, red for DELETE
const ACTION_BADGE: Record<string, string> = {
  CREATE: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  UPDATE: 'bg-amber-50 text-amber-700 border-amber-200',
  DELETE: 'bg-rose-50 text-rose-700 border-rose-200',
};

// Pretty-print a JSON value as a readable side-by-side diff view
function DiffView({
  label,
  value,
  accent,
}: {
  label: string;
  value: Record<string, unknown> | null;
  accent: string;
}) {
  if (!value) {
    return (
      <div className="flex-1">
        <p className={`text-xs font-semibold ${accent} mb-2 uppercase tracking-wide`}>{label}</p>
        <p className="text-sm text-slate-400 italic">No data</p>
      </div>
    );
  }

  return (
    <div className="flex-1 min-w-0">
      <p className={`text-xs font-semibold ${accent} mb-2 uppercase tracking-wide`}>{label}</p>
      <div className="bg-slate-50/80 rounded-xl border border-slate-100 p-3 space-y-1.5">
        {Object.entries(value).map(([key, val]) => (
          <div key={key} className="flex justify-between gap-3 text-sm">
            <span className="text-slate-500 font-medium truncate">{key}</span>
            <span className="text-slate-800 font-semibold text-right break-all">
              {typeof val === 'object' && val !== null ? JSON.stringify(val) : String(val ?? '—')}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================================================================
// AuditEntryCard — one audit log row. Expandable to show old/new values.
// ============================================================================
function AuditEntryCard({ entry }: { entry: AuditLogItem }) {
  const [expanded, setExpanded] = useState(false);
  const hasDiff = entry.old_value || entry.new_value;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="p-[1px] bg-gradient-to-br from-blue-200/40 via-rose-200/30 to-amber-200/40 rounded-[1.5rem]"
    >
      <div className="bg-white/80 backdrop-blur-3xl rounded-[calc(1.5rem-1px)] p-5 space-y-3">
        {/* Main row — timestamp, entity, action badge */}
        <button
          onClick={() => hasDiff && setExpanded(!expanded)}
          className="w-full text-left"
        >
          <div className="flex items-center justify-between gap-4">
            <div className="min-w-0 flex-1">
              <p className="text-sm text-slate-400">{formatTimestamp(entry.timestamp)}</p>
              <p className="font-bold text-slate-900 mt-0.5 truncate">
                {entityLabel(entry.entity_type)}{' '}
                <span className="font-mono text-slate-600">{entry.entity_id}</span>
              </p>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              <span
                className={`inline-flex items-center px-2.5 py-1 rounded-full border text-xs font-semibold ${
                  ACTION_BADGE[entry.action_type] ?? 'bg-slate-50 text-slate-600 border-slate-200'
                }`}
              >
                {entry.action_type}
              </span>
              {hasDiff && (
                <motion.div
                  animate={{ rotate: expanded ? 180 : 0 }}
                  transition={{ duration: 0.2 }}
                >
                  <ChevronDown size={16} className="text-slate-400" />
                </motion.div>
              )}
            </div>
          </div>
        </button>

        {/* Expandable diff section — old vs new, side by side */}
        <AnimatePresence>
          {expanded && hasDiff && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25 }}
              className="overflow-hidden"
            >
              <div className="border-t border-slate-100 pt-4 flex flex-col sm:flex-row gap-4">
                <DiffView label="Before" value={entry.old_value} accent="text-slate-500" />
                <DiffView label="After" value={entry.new_value} accent="text-indigo-600" />
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

// ============================================================================
// Main Page Component
// ============================================================================
export default function AuditLogPage() {
  const [entries, setEntries] = useState<AuditLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Pagination state
  const LIMIT = 20;
  const [offset, setOffset] = useState(0);

  // Filter state
  const [entityType, setEntityType] = useState('');
  const [actionType, setActionType] = useState('');

  const fetchLogs = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams({ limit: String(LIMIT), offset: String(offset) });
      if (entityType) params.set('entity_type', entityType);
      if (actionType) params.set('action_type', actionType);

      const res = await fetch(`/api/v1/audit-logs?${params.toString()}`, {
        headers: { 'X-Tenant-ID': 'PHARM-001' },
      });

      if (!res.ok) throw new Error('Failed to load audit logs');
      const data: AuditLogsResponse = await res.json();
      setEntries(data.items);
      setTotal(data.total);
    } catch (err: any) {
      setError(err.message || 'Something went wrong');
    } finally {
      setIsLoading(false);
    }
  }, [offset, entityType, actionType]);

  useEffect(() => {
    fetchLogs();
  }, [fetchLogs]);

  // Reset to page 1 when filters change
  const handleFilterChange = (setter: (v: string) => void) => (value: string) => {
    setter(value);
    setOffset(0);
  };

  const totalPages = Math.max(1, Math.ceil(total / LIMIT));
  const currentPage = Math.floor(offset / LIMIT) + 1;

  return (
    <div className="relative min-h-screen bg-[#fdfbfb] text-slate-800 overflow-x-hidden selection:bg-blue-100 font-sans antialiased">

      {/* ETHEREAL BIOLOGICAL ORBS — same as other pages */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none flex items-center justify-center z-0">
        <motion.div
          animate={{ rotate: 360, scale: [1, 1.05, 1] }}
          transition={{ duration: 30, repeat: Infinity, ease: "linear" }}
          className="absolute w-[800px] h-[800px] bg-rose-100/50 blur-[120px] rounded-full will-change-transform translate-x-1/4 -translate-y-1/4 mix-blend-multiply"
        />
        <motion.div
          animate={{ rotate: -360, scale: [1, 1.1, 1] }}
          transition={{ duration: 40, repeat: Infinity, ease: "linear" }}
          className="absolute w-[600px] h-[600px] bg-blue-100/50 blur-[120px] rounded-full will-change-transform -translate-x-1/4 translate-y-1/4 mix-blend-multiply"
        />
      </div>

      <div className="relative z-10 max-w-[1200px] mx-auto p-6 md:p-10 min-h-screen flex flex-col">

        {/* HEADER */}
        <header className="flex justify-between items-center mb-10">
          <div className="flex items-center gap-4">
            <BackButton href="/pos" />
            <div>
              <h1 className="text-2xl font-bold text-slate-900">Audit Log</h1>
              <p className="text-slate-500 mt-1">Track all changes across your pharmacy.</p>
            </div>
          </div>
        </header>

        {/* FILTER CONTROLS */}
        <div className="flex flex-wrap items-center gap-3 mb-6">
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <Filter size={16} />
            <span className="font-medium">Filters</span>
          </div>

          <select
            value={entityType}
            onChange={(e) => handleFilterChange(setEntityType)(e.target.value)}
            className="px-3 py-2 bg-white/60 backdrop-blur-md border border-white/80 shadow-sm rounded-xl text-sm text-slate-700 font-medium focus:outline-none focus:ring-2 focus:ring-indigo-200 transition-colors appearance-none cursor-pointer"
          >
            <option value="">All entity types</option>
            <option value="purchase_order">Purchase Order</option>
            <option value="medication_batch">Medication Batch</option>
            <option value="patient">Patient</option>
          </select>

          <select
            value={actionType}
            onChange={(e) => handleFilterChange(setActionType)(e.target.value)}
            className="px-3 py-2 bg-white/60 backdrop-blur-md border border-white/80 shadow-sm rounded-xl text-sm text-slate-700 font-medium focus:outline-none focus:ring-2 focus:ring-indigo-200 transition-colors appearance-none cursor-pointer"
          >
            <option value="">All actions</option>
            <option value="CREATE">Created</option>
            <option value="UPDATE">Updated</option>
            <option value="DELETE">Deleted</option>
          </select>

          <span className="text-sm text-slate-400 ml-1">
            {total} {total === 1 ? 'entry' : 'entries'}
          </span>
        </div>

        {/* CONTENT */}
        <div className="flex-1 space-y-4">
          {isLoading ? (
            // Loading skeleton — matches the app's pulse animation convention
            <div className="space-y-4">
              {[1, 2, 3].map((n) => (
                <div key={n} className="bg-white rounded-[1.5rem] shadow-sm border border-slate-100 p-6 space-y-3">
                  <div className="h-4 bg-slate-200 rounded animate-pulse w-1/4" />
                  <div className="h-5 bg-slate-200 rounded animate-pulse w-1/2" />
                </div>
              ))}
            </div>
          ) : error ? (
            // Error state
            <div className="bg-white rounded-3xl shadow-sm border border-slate-100 p-10 text-center">
              <ScrollText className="mx-auto mb-3 text-slate-300" size={32} />
              <p className="font-semibold text-slate-600">Couldn't load audit logs</p>
              <p className="text-sm text-slate-400 mt-1">{error}</p>
              <button
                onClick={fetchLogs}
                className="mt-4 px-4 py-2 bg-white/60 backdrop-blur-md border border-slate-200 text-slate-600 rounded-xl text-sm font-semibold hover:bg-white transition-colors"
              >
                Try again
              </button>
            </div>
          ) : entries.length === 0 ? (
            // Empty state
            <div className="bg-white rounded-3xl shadow-sm border border-slate-100 p-10 text-center">
              <ScrollText className="mx-auto mb-3 text-slate-300" size={32} />
              <p className="font-semibold text-slate-600">No audit activity yet</p>
              <p className="text-sm text-slate-400 mt-1">
                Audit entries appear here when orders are created, updated, or other changes are made.
              </p>
            </div>
          ) : (
            // Audit log entries
            <div className="space-y-3">
              {entries.map((entry) => (
                <AuditEntryCard key={entry.id} entry={entry} />
              ))}
            </div>
          )}
        </div>

        {/* PAGINATION CONTROLS */}
        {total > LIMIT && (
          <div className="flex items-center justify-center gap-3 mt-8">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - LIMIT))}
              className="p-2.5 bg-white/60 backdrop-blur-md border border-white/80 shadow-sm rounded-2xl text-slate-500 hover:text-slate-800 hover:bg-white transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ChevronLeft size={18} />
            </button>
            <span className="text-sm font-medium text-slate-500">
              Page {currentPage} of {totalPages}
            </span>
            <button
              disabled={currentPage >= totalPages}
              onClick={() => setOffset(offset + LIMIT)}
              className="p-2.5 bg-white/60 backdrop-blur-md border border-white/80 shadow-sm rounded-2xl text-slate-500 hover:text-slate-800 hover:bg-white transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ChevronRight size={18} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
