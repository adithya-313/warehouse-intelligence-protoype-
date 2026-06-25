"use client";

import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { TrendingDown, Truck, ShieldAlert, AlertOctagon, CheckCircle2 } from 'lucide-react';
import { cn } from '@/lib/utils';

export default function Scorecard({ supplierId = "SUPP-001" }: { supplierId?: string }) {
  const [data, setData] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchScorecard = async () => {
      try {
        const res = await fetch(`/api/v1/suppliers/${supplierId}/scorecard`);
        if (!res.ok) throw new Error("No data");
        const json = await res.json();
        setData(json);
      } catch (err) {
        setData({
          supplier_id: supplierId,
          name: "Apex Pharma Distributors (DEMO)",
          financial_loss_rupees: 14500,
          delivery_success_rate: 82,
          trust_score: 65,
          risk_level: "HIGH",
          recent_failures: 3
        });
      } finally {
        setIsLoading(false);
      }
    };
    fetchScorecard();
  }, [supplierId]);

  if (isLoading) return <div className="animate-pulse h-64 bg-gray-100 dark:bg-gray-800 rounded-2xl"></div>;

  const isHighRisk = data.risk_level === "HIGH" || data.trust_score < 70;

  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-3xl p-8 shadow-xl max-w-4xl mx-auto"
    >
      <div className="flex justify-between items-start mb-8">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            {data.name}
            {isHighRisk ? <ShieldAlert className="text-red-500" /> : <CheckCircle2 className="text-green-500" />}
          </h2>
          <p className="text-gray-500 text-sm mt-1">ID: {data.supplier_id} | Real-time Vendor Telemetry</p>
        </div>
        <div className={cn(
          "px-4 py-1.5 rounded-full text-sm font-bold tracking-wider",
          isHighRisk ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"
        )}>
          {data.risk_level || (isHighRisk ? "HIGH RISK" : "TRUSTED")}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <motion.div 
          whileHover={{ scale: 1.02 }}
          className="bg-gradient-to-br from-red-50 to-rose-100 dark:from-red-900/20 dark:to-rose-900/20 p-6 rounded-2xl border border-red-100 dark:border-red-900/30"
        >
          <div className="flex items-center gap-3 text-red-600 dark:text-red-400 mb-2">
            <TrendingDown size={20} />
            <h3 className="font-semibold">Financial Loss</h3>
          </div>
          <p className="text-4xl font-black text-red-700 dark:text-red-500">
            ₹{data.financial_loss_rupees.toLocaleString()}
          </p>
          <p className="text-xs text-red-600/80 mt-2 font-medium">Capital dropped due to shortfalls</p>
        </motion.div>

        <motion.div 
          whileHover={{ scale: 1.02 }}
          className="bg-gray-50 dark:bg-gray-800/50 p-6 rounded-2xl border border-gray-100 dark:border-gray-800"
        >
          <div className="flex items-center gap-3 text-blue-600 dark:text-blue-400 mb-2">
            <Truck size={20} />
            <h3 className="font-semibold">Delivery SLA</h3>
          </div>
          <p className="text-4xl font-black text-gray-900 dark:text-white">
            {data.delivery_success_rate}%
          </p>
          <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2 mt-3">
            <div className={cn("h-2 rounded-full", data.delivery_success_rate > 90 ? "bg-green-500" : "bg-yellow-500")} style={{ width: `${data.delivery_success_rate}%` }}></div>
          </div>
        </motion.div>

        <motion.div 
          whileHover={{ scale: 1.02 }}
          className="bg-gray-50 dark:bg-gray-800/50 p-6 rounded-2xl border border-gray-100 dark:border-gray-800"
        >
          <div className="flex items-center gap-3 text-indigo-600 dark:text-indigo-400 mb-2">
            <AlertOctagon size={20} />
            <h3 className="font-semibold">Trust Score</h3>
          </div>
          <p className="text-4xl font-black text-gray-900 dark:text-white">
            {data.trust_score}/100
          </p>
          <p className="text-xs text-gray-500 mt-2 font-medium">{data.recent_failures} recent SLA breaches</p>
        </motion.div>
      </div>
    </motion.div>
  );
}
