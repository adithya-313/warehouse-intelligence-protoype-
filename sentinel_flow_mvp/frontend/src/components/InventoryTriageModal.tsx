"use client";

// [STORY: THE TRIAGE MODAL]
// Chapter 2: The Glass Command Center
// When the pharmacist clicks the Package icon, we don't take them to a new page.
// We overlay a blurred-glass modal. It shows the financial risk at the top,
// and lists the most critical inventory items first.
// They press 'Escape' or click 'X' to instantly return to the patient in front of them.

import React, { useEffect, useState } from 'react';
import { api } from '../services/api';
import { X, AlertOctagon, AlertTriangle, CheckCircle } from 'lucide-react';

interface TriageItem {
  sku_id: string;
  total_stock: number;
  closest_expiry: string;
  urgency_level: "CRITICAL" | "WARNING" | "HEALTHY";
}

interface TriageMetrics {
  total_value_inr: number;
  capital_at_risk_inr: number;
  out_of_stock_skus: number;
}

interface TriageResponse {
  metrics: TriageMetrics;
  items: TriageItem[];
}

interface InventoryTriageModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const InventoryTriageModal: React.FC<InventoryTriageModalProps> = ({ isOpen, onClose }) => {
  const [data, setData] = useState<TriageResponse | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!isOpen) return;

    const fetchTriage = async () => {
      setLoading(true);
      try {
        const result = await api.get('/api/v1/inventory/triage') as TriageResponse;
        setData(result);
      } catch (error) {
        console.error("Failed to load triage data", error);
      } finally {
        setLoading(false);
      }
    };

    fetchTriage();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-8">
      <div className="bg-gray-900 border border-gray-700 w-full max-w-5xl h-[85vh] rounded-2xl shadow-2xl flex flex-col overflow-hidden">

        {/* Header Section */}
        <div className="flex justify-between items-center p-6 border-b border-gray-800 bg-gray-950">
          <h2 className="text-2xl font-bold text-white flex items-center gap-2">
            Inventory Intelligence <span className="text-sm font-normal text-gray-500 px-3 py-1 bg-gray-800 rounded-full">Triage Mode</span>
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
            <X size={28} />
          </button>
        </div>

        {loading ? (
          <div className="flex-1 flex items-center justify-center text-gray-400 animate-pulse text-lg">
            Running Aggregations...
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto p-6 space-y-6">

            {/* Financial Telemetry Banner */}
            <div className="grid grid-cols-3 gap-4 mb-8">
              <div className="bg-gray-800 p-4 rounded-xl border border-gray-700">
                <p className="text-gray-400 text-sm uppercase tracking-wider mb-1">Total Asset Value</p>
                <p className="text-2xl font-mono text-white">
                  ₹{data?.metrics?.total_value_inr?.toFixed(2)}
                </p>
              </div>
              <div className="bg-red-950/30 p-4 rounded-xl border border-red-900/50">
                <p className="text-red-400 text-sm uppercase tracking-wider mb-1">Capital at Risk ({"<"} 30 days)</p>
                <p className="text-2xl font-mono text-red-500">
                  ₹{data?.metrics?.capital_at_risk_inr?.toFixed(2)}
                </p>
              </div>
              <div className="bg-gray-800 p-4 rounded-xl border border-gray-700">
                <p className="text-gray-400 text-sm uppercase tracking-wider mb-1">Out of Stock SKUs</p>
                <p className="text-2xl font-mono text-white">{data?.metrics?.out_of_stock_skus}</p>
              </div>
            </div>

            {/* Action Swimlanes */}
            <div className="space-y-2">
              {data?.items?.map((item) => {
                let Icon = CheckCircle;
                let color = "text-green-500";
                let bg = "bg-gray-800/50";

                if (item.urgency_level === "CRITICAL") {
                  Icon = AlertOctagon;
                  color = "text-red-500";
                  bg = "bg-red-950/20 border border-red-900/30";
                }
                if (item.urgency_level === "WARNING") {
                  Icon = AlertTriangle;
                  color = "text-orange-500";
                  bg = "bg-orange-950/20 border border-orange-900/30";
                }

                return (
                  <div key={item.sku_id} className={`flex items-center justify-between p-4 rounded-lg ${bg}`}>
                    <div className="flex items-center gap-4">
                      <Icon className={color} size={24} />
                      <div>
                        <p className="text-lg font-bold text-white">{item.sku_id}</p>
                        <p className="text-sm text-gray-400">
                          Closest Expiry: {item.closest_expiry}
                        </p>
                      </div>
                    </div>
                    <div className="text-right">
                      <p className={`text-2xl font-mono font-bold ${color}`}>{item.total_stock}</p>
                      <p className="text-xs text-gray-500 uppercase">Total Units</p>
                    </div>
                  </div>
                );
              })}
            </div>

          </div>
        )}
      </div>
    </div>
  );
};
