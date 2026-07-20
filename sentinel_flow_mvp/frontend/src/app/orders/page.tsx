"use client";

import React, { useEffect, useState } from 'react';
import { Package, Clock, CheckCircle, AlertTriangle } from 'lucide-react';
import { api } from '@/services/api';
import BackButton from '@/components/ui/BackButton';

export default function OrderLedgerPage() {
  const [orders, setOrders] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchOrders = async () => {
      try {
        const response = await api.get('/api/v1/purchase-orders');
        setOrders(response);
      } catch (error) {
        console.error("Failed to fetch order ledger", error);
      } finally {
        setIsLoading(false);
      }
    };
    fetchOrders();
  }, []);

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'FULFILLED':
        return <span className="flex items-center gap-1 px-3 py-1 bg-green-100 text-green-700 rounded-full text-xs font-bold"><CheckCircle size={14} /> FULFILLED</span>;
      case 'SUBMITTED':
        return <span className="flex items-center gap-1 px-3 py-1 bg-blue-100 text-blue-700 rounded-full text-xs font-bold"><Clock size={14} /> IN TRANSIT</span>;
      default:
        return <span className="flex items-center gap-1 px-3 py-1 bg-slate-100 text-slate-700 rounded-full text-xs font-bold"><AlertTriangle size={14} /> {status}</span>;
    }
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      <div className="flex items-center gap-4">
        <BackButton href="/pos" />
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Global Order Ledger</h1>
          <p className="text-slate-500 mt-1">Track all inbound manifests and capital allocation.</p>
        </div>
      </div>

      <div className="bg-white rounded-3xl shadow-sm border border-slate-200 overflow-hidden">
        {isLoading ? (
          <div className="p-10 text-center text-slate-500">Loading ledger data...</div>
        ) : orders.length === 0 ? (
          <div className="p-10 text-center text-slate-500">No purchase orders found.</div>
        ) : (
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-sm font-semibold text-slate-600">
                <th className="p-4">PO ID</th>
                <th className="p-4">Vendor ID</th>
                <th className="p-4">Order Date</th>
                <th className="p-4">Expected Delivery</th>
                <th className="p-4">Line Items</th>
                <th className="p-4">Capital Value</th>
                <th className="p-4">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {orders.map((order, idx) => (
                <tr key={idx} className="hover:bg-slate-50 transition-colors">
                  <td className="p-4 font-mono text-sm font-medium text-indigo-600">{order.po_id}</td>
                  <td className="p-4 font-medium text-slate-700">{order.supplier_id}</td>
                  <td className="p-4 text-slate-600">{new Date(order.order_date).toLocaleDateString()}</td>
                  <td className="p-4 text-slate-600">{new Date(order.expected_delivery_date).toLocaleDateString()}</td>
                  <td className="p-4 text-slate-600 font-medium">{order.item_count} items</td>
                  <td className="p-4 font-bold text-slate-800">₹{order.total_value_rupees.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                  <td className="p-4">{getStatusBadge(order.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
