"use client";

import React, { useEffect, useState } from 'react';
import { api } from '@/services/api';
import type { TransactionHistoryItem } from '@/services/api';
import Link from 'next/link';
import { ArrowLeft, Clock } from 'lucide-react';
import ScreenAtmosphere from '@/components/ui/core/ScreenAtmosphere';
import TransactionMatrix from '@/components/ui/core/TransactionMatrix';
import LedgerRow from '@/components/ui/core/LedgerRow';

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
          <Link 
            href="/pos" 
            className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white/70 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10 rounded-full transition-all duration-200 backdrop-blur-md"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to POS
          </Link>
          <h1 className="text-2xl font-bold flex items-center gap-2 text-white/90">
            <Clock className="w-6 h-6 text-emerald-400" />
            Transaction Ledger
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
              <td colSpan={5} className="py-12 text-center text-white/40">
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
