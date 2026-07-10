"use client";

import React, { useEffect, useState } from 'react';
import { api } from '@/services/api';
import type { TransactionHistoryItem } from '@/services/api';
import { Clock } from 'lucide-react';
import ScreenAtmosphere from '@/components/ui/core/ScreenAtmosphere';
import TransactionMatrix from '@/components/ui/core/TransactionMatrix';
import LedgerRow from '@/components/ui/core/LedgerRow';
import BackButton from '@/components/ui/BackButton';

export default function HistoryPage() {
  const [transactions, setTransactions] = useState<TransactionHistoryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function loadHistory() {
      setIsLoading(true);
      try {
        const data = await api.fetchTransactionHistory();
        setTransactions(data);
      } catch (error) {
        console.error("Failed to fetch history:", error);
      } finally {
        setIsLoading(false);
      }
    }
    loadHistory();
  }, []);

  return (
    <ScreenAtmosphere>
      <div className="relative z-10 container mx-auto px-6 py-12 max-w-6xl">
        
        {/* Sleek, Minimal Header */}
        <div className="flex items-center gap-4 mb-8">
          <BackButton href="/pos" label="Back to POS" />
          <h1 className="text-2xl font-bold flex items-center gap-2 text-slate-900">
            <Clock className="w-6 h-6 text-emerald-400" />
            Transaction History
          </h1>
        </div>

        {/* Core Matrix Component */}
        <TransactionMatrix>
          {isLoading ? (
            <tr>
              <td colSpan={5} className="py-12 text-center text-white/40">
                <div className="animate-pulse">Loading secure ledger data...</div>
              </td>
            </tr>
          ) : transactions.length === 0 ? (
            <tr>
              <td colSpan={5} className="py-12 text-center text-slate-400">
                No transactions found.
              </td>
            </tr>
          ) : (
            transactions.map(tx => (
              <LedgerRow key={tx.id} transaction={tx} />
            ))
          )}
        </TransactionMatrix>

      </div>
    </ScreenAtmosphere>
  );
}
