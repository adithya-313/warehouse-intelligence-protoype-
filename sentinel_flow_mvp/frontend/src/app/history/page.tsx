"use client";

import React, { useEffect, useState } from 'react';
import { api, TransactionHistoryItem } from '@/services/api';
import SpatialBackground from '@/components/ui/ledger/SpatialBackground';
import GlassmorphicTable from '@/components/ui/ledger/GlassmorphicTable';

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
    <div className="relative min-h-screen w-full overflow-hidden bg-black text-white antialiased selection:bg-purple-500/30">
      <SpatialBackground />
      <main className="relative z-10 container mx-auto p-6">
        <GlassmorphicTable
          transactions={transactions}
          isLoading={isLoading}
        />
      </main>
    </div>
  );
}
