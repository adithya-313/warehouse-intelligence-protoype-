"use client";

import React, { useState, useEffect } from 'react';
import ReactDOM from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { X, History } from 'lucide-react';
import { api } from '@/services/api';
import { getStatusBadge, getDelayBadge } from '@/utils/orderBadges';
import { calculateDaysLate } from '@/utils/orderDelay';

export const VendorHistoryPanel: React.FC<any> = ({ isOpen, onClose, supplierId, supplierName }) => {
  const [orders, setOrders] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortByDelayed, setSortByDelayed] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (isOpen) {
      fetchHistory();
    }
  }, [isOpen, supplierId]);

  const fetchHistory = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const response = await api.get(`/api/v1/suppliers/${supplierId}/orders`);
      setOrders(response);
    } catch (err: any) {
      setError(err.message || 'Failed to load order history.');
    } finally {
      setIsLoading(false);
    }
  };

  const processedOrders = orders.map((order) => {
    const daysLate = calculateDaysLate(order.status, order.expected_delivery_date, order.actual_delivery_date);
    return { ...order, daysLate };
  });

  if (sortByDelayed) {
    processedOrders.sort((a, b) => b.daysLate - a.daysLate);
  }

  const panelContent = (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-slate-900/20 backdrop-blur-sm z-[100]"
          />
          <motion.div
            initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 25, stiffness: 200 }}
            className="fixed right-0 top-0 bottom-0 w-full max-w-4xl bg-white shadow-2xl z-[101] border-l border-slate-200 flex flex-col"
          >
            <div className="p-6 border-b flex justify-between bg-slate-50 items-center">
              <div>
                <h2 className="text-xl font-bold flex items-center gap-2"><History className="text-indigo-600" /> Order History Drill-Down</h2>
                <p className="text-sm text-slate-500 mt-1">Vendor: <span className="font-bold">{supplierName}</span></p>
              </div>
              <div className="flex items-center gap-4">
                <label className="flex items-center gap-2 text-sm font-medium text-slate-700 cursor-pointer">
                  <input 
                    type="checkbox" 
                    checked={sortByDelayed} 
                    onChange={() => setSortByDelayed(!sortByDelayed)}
                    className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500" 
                  />
                  Most Delayed First
                </label>
                <button onClick={onClose} className="p-2 hover:bg-slate-200 rounded-full"><X size={20} /></button>
              </div>
            </div>

            <div className="p-0 flex-1 overflow-y-auto">
              {isLoading ? (
                <div className="w-full flex flex-col items-center justify-center h-64 gap-4">
                  <div className="w-8 h-8 border-4 border-indigo-200 border-t-indigo-500 rounded-full animate-spin" />
                  <p className="text-slate-500 font-medium animate-pulse">Loading history...</p>
                </div>
              ) : error ? (
                <div className="p-10 text-center text-rose-500 font-medium">
                  {error}
                </div>
              ) : processedOrders.length === 0 ? (
                <div className="p-10 text-center text-slate-500 font-medium">
                  No historical orders found for this vendor.
                </div>
              ) : (
                <table className="w-full table-fixed text-left border-collapse">
                  <thead>
                    <tr className="bg-white border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase tracking-wider sticky top-0 z-10 shadow-sm">
                      <th className="p-4 w-[16%]">Date</th>
                      <th className="p-4 w-[16%]">PO ID</th>
                      <th className="p-4 w-[14%]">SKU</th>
                      <th className="p-4 w-[24%]">Status & Delay</th>
                      <th className="p-4 w-[15%]">Volume</th>
                      <th className="p-4 w-[15%]">Value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {processedOrders.map((order, idx) => (
                      <motion.tr 
                        key={`${order.po_id}-${order.sku_id}-${idx}`}
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: idx * 0.03 }}
                        className="hover:bg-slate-50 transition-colors"
                      >
                        <td className="p-4 text-sm text-slate-600">{new Date(order.order_date).toLocaleDateString()}</td>
                        <td className="p-4 font-mono text-xs font-medium text-indigo-600 truncate">{order.po_id}</td>
                        <td className="p-4 text-sm font-medium text-slate-700">{order.sku_id}</td>
                        <td className="p-4">
                          <div className="flex items-center gap-2 flex-wrap">
                            {getStatusBadge(order.status)}
                            {getDelayBadge(order.daysLate)}
                          </div>
                        </td>
                        <td className="p-4 text-sm text-slate-600">
                          {order.delivered_qty} / {order.ordered_qty}
                        </td>
                        <td className="p-4 text-sm font-bold text-slate-800">
                          ₹{((order.ordered_qty || 0) * (order.expected_mrp || 0)).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                        </td>
                      </motion.tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );

  if (!mounted) return null;
  return ReactDOM.createPortal(panelContent, document.body);
};
