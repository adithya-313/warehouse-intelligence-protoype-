"use client";

import React, { useEffect, useState } from 'react';
import { api, TransactionHistoryItem } from '@/services/api';
import Link from 'next/link';
import { ArrowLeft, Clock } from 'lucide-react';

export default function HistoryPage() {
  const [history, setHistory] = useState<TransactionHistoryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function loadHistory() {
      setIsLoading(true);
      try {
        const data = await api.fetchTransactionHistory();
        setHistory(data);
      } catch (error) {
        console.error("Failed to fetch history:", error);
      } finally {
        setIsLoading(false);
      }
    }
    loadHistory();
  }, []);

  const formatDate = (isoString: string) => {
    const d = new Date(isoString);
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const month = months[d.getMonth()];
    const day = d.getDate();
    const year = d.getFullYear();
    const hours = d.getHours().toString().padStart(2, '0');
    const minutes = d.getMinutes().toString().padStart(2, '0');
    return `${month} ${day}, ${year} - ${hours}:${minutes}`;
  };

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white/90 p-8">
      <div className="max-w-6xl mx-auto">
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

        <div className="rounded-xl border border-white/10 overflow-hidden bg-[#0a0a0a]">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-white/10 text-white/50 text-sm uppercase tracking-wider">
                <th className="px-6 py-4 font-medium">Date / Time</th>
                <th className="px-6 py-4 font-medium">Receipt ID</th>
                <th className="px-6 py-4 font-medium">Customer Name</th>
                <th className="px-6 py-4 font-medium">Phone Number</th>
                <th className="px-6 py-4 font-medium text-right">Total Amount</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="border-b border-white/5 last:border-0 animate-pulse">
                    <td className="px-6 py-4"><div className="h-4 bg-white/5 rounded w-3/4"></div></td>
                    <td className="px-6 py-4"><div className="h-4 bg-white/5 rounded w-1/2"></div></td>
                    <td className="px-6 py-4"><div className="h-6 bg-white/5 rounded-full w-24"></div></td>
                    <td className="px-6 py-4"><div className="h-4 bg-white/5 rounded w-3/4"></div></td>
                    <td className="px-6 py-4"><div className="h-4 bg-white/5 rounded w-1/2 ml-auto"></div></td>
                  </tr>
                ))
              ) : history.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center text-white/40">
                    No transactions found.
                  </td>
                </tr>
              ) : (
                history.map((tx) => (
                  <tr key={tx.id} className="border-b border-white/5 last:border-0 hover:bg-white/5 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap text-white/70 text-sm">
                      {formatDate(tx.timestamp)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap font-mono text-sm text-emerald-400/80">
                      {tx.id.split('-')[0]}...
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {tx.customer_name === "Anonymous" ? (
                        <span className="px-3 py-1 bg-white/5 text-white/40 rounded-full text-xs font-medium border border-white/10">
                          Anonymous
                        </span>
                      ) : (
                        <span className="font-medium text-white/90">{tx.customer_name}</span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-white/60 text-sm">
                      {tx.customer_phone || "-"}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right font-bold text-emerald-400">
                      ₹{tx.total_amount_inr.toFixed(2)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
