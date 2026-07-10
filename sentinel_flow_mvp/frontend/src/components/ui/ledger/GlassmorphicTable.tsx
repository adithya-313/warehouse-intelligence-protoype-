"use client";

import React from 'react';
import { motion } from 'framer-motion';
import { Clock, ArrowLeft } from 'lucide-react';
import Link from 'next/link';
import type { TransactionHistoryItem } from '@/services/api';

/*
 * ─── GlassmorphicTable ────────────────────────────────────────────────────
 *
 * A presentation-only component that renders the Transaction Ledger as a
 * glassmorphic table with kinetic row-entry animations.
 *
 * Glassmorphism recipe:
 *   background:  bg-white/5  (translucent base)
 *   blur:        backdrop-blur-xl
 *   border:      1px solid white/10  (the "brutalist" 1px line)
 *
 * Row animation:
 *   Each <tr> is a Framer Motion <motion.tr> that fades in and slides up
 *   with a staggered delay based on its index. This gives a "cascade" feel
 *   without any imperative scroll listeners.
 *
 * Loading skeleton:
 *   Uses the same glassmorphic card with shimmering pulse placeholders.
 *   Shimmer is achieved via Tailwind's `animate-pulse` combined with a
 *   CSS gradient overlay that sweeps left-to-right (see globals.css for
 *   the optional `.shimmer` class — we use `animate-pulse` here for
 *   zero extra CSS).
 *
 * Props:
 *   transactions  –  TransactionHistoryItem[]  –  data to render
 *   isLoading     –  boolean                  –  show skeleton when true
 */

// ─── Helpers ──────────────────────────────────────────────────────────────

function formatDate(isoString: string) {
  const d = new Date(isoString);
  const months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];
  const month = months[d.getMonth()];
  const day = d.getDate();
  const year = d.getFullYear();
  const hours = d.getHours().toString().padStart(2, '0');
  const minutes = d.getMinutes().toString().padStart(2, '0');
  return `${month} ${day}, ${year} — ${hours}:${minutes}`;
}

// ─── Skeleton row ─────────────────────────────────────────────────────────

function SkeletonRow({ index }: { index: number }) {
  return (
    <motion.tr
      key={`skeleton-${index}`}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ delay: index * 0.05 }}
      className="border-b border-white/5 last:border-0"
    >
      <td className="px-6 py-4">
        <div className="h-4 bg-white/5 rounded w-3/4 animate-pulse" />
      </td>
      <td className="px-6 py-4">
        <div className="h-4 bg-white/5 rounded w-1/2 animate-pulse" />
      </td>
      <td className="px-6 py-4">
        <div className="h-6 bg-white/5 rounded-full w-24 animate-pulse" />
      </td>
      <td className="px-6 py-4">
        <div className="h-4 bg-white/5 rounded w-3/4 animate-pulse" />
      </td>
      <td className="px-6 py-4">
        <div className="h-4 bg-white/5 rounded w-1/2 ml-auto animate-pulse" />
      </td>
    </motion.tr>
  );
}

// ─── Data row ─────────────────────────────────────────────────────────────

function DataRow({
  tx,
  index,
}: {
  tx: TransactionHistoryItem;
  index: number;
}) {
  return (
    <motion.tr
      key={tx.id}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04, duration: 0.35, ease: 'easeOut' }}
      className="border-b border-white/5 last:border-0 hover:bg-white/[0.08] transition-colors"
    >
      <td className="text-sm text-gray-100 py-4 border-b border-white/5 whitespace-nowrap">
        {formatDate(tx.timestamp)}
      </td>
      <td className="text-sm text-gray-100 py-4 border-b border-white/5 whitespace-nowrap text-emerald-400 font-mono">
        {tx.id.split('-')[0]}...
      </td>
      <td className="text-sm text-gray-100 py-4 border-b border-white/5 whitespace-nowrap">
        {tx.customer_name === 'Anonymous' ? (
          <span className="px-3 py-1 bg-white/5 text-white/40 rounded-full text-xs font-medium border border-white/10">
            Anonymous
          </span>
        ) : (
          <span className="font-medium text-white/90">
            {tx.customer_name}
          </span>
        )}
      </td>
      <td className="text-sm text-gray-100 py-4 border-b border-white/5 whitespace-nowrap">
        {tx.customer_phone || '—'}
      </td>
      <td className="text-sm text-gray-100 py-4 border-b border-white/5 whitespace-nowrap text-right text-emerald-400 font-mono">
        ₹{tx.total_amount_inr.toFixed(2)}
      </td>
    </motion.tr>
  );
}

// ─── Empty state ──────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <motion.tr
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.4 }}
    >
      <td
        colSpan={5}
        className="px-6 py-12 text-center text-white/40"
      >
        No transactions found.
      </td>
    </motion.tr>
  );
}

// ─── Public component ─────────────────────────────────────────────────────

interface GlassmorphicTableProps {
  transactions: TransactionHistoryItem[];
  isLoading: boolean;
}

export default function GlassmorphicTable({
  transactions,
  isLoading,
}: GlassmorphicTableProps) {
  return (
    <div>
      {/* Header row */}
      <div className="flex items-center gap-4 mb-8">
        <Link
          href="/pos"
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white/70 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10 rounded-full transition-all duration-200 backdrop-blur-md"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to POS
        </Link>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Clock className="w-6 h-6 text-emerald-400" />
          Transaction Ledger
        </h1>
      </div>

      {/* Glassmorphic table container */}
      <div className="relative z-10 w-full rounded-2xl bg-black/40 backdrop-blur-3xl border border-white/10 shadow-2xl p-6">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr>
              <th className="text-xs font-semibold text-gray-400 tracking-wider uppercase border-b border-white/10 pb-4">Date / Time</th>
              <th className="text-xs font-semibold text-gray-400 tracking-wider uppercase border-b border-white/10 pb-4">Receipt ID</th>
              <th className="text-xs font-semibold text-gray-400 tracking-wider uppercase border-b border-white/10 pb-4">Customer Name</th>
              <th className="text-xs font-semibold text-gray-400 tracking-wider uppercase border-b border-white/10 pb-4">Phone Number</th>
              <th className="text-xs font-semibold text-gray-400 tracking-wider uppercase border-b border-white/10 pb-4 text-right">Total Amount</th>
            </tr>
          </thead>
          <tbody>
            {isLoading
              ? Array.from({ length: 5 }).map((_, i) => (
                  <SkeletonRow key={i} index={i} />
                ))
              : transactions.length === 0
                ? <EmptyState />
                : transactions.map((tx, i) => (
                    <DataRow key={tx.id} tx={tx} index={i} />
                  ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
