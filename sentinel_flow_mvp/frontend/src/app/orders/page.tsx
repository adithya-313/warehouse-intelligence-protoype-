"use client";

import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
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

  // This is the container for all the order rows.
  // We tell it to wait 0.05 seconds between showing each row,
  // so the rows "cascade" in one after another instead of all
  // popping in at once.
  const rowContainerVariants: Variants = {
    hidden: {},
    visible: {
      transition: {
        staggerChildren: 0.05,
      },
    },
  };

  // This describes how each individual row enters the screen.
  // It starts slightly below its final position (y: 16) and invisible,
  // then springs up into place — matching the same spring feel used
  // in the app's global template.tsx and ClinicalCompanion.tsx.
  const singleRowVariants: Variants = {
    hidden: { opacity: 0, y: 16 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { type: "spring", stiffness: 260, damping: 20 },
    },
  };

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
        {/*
        AnimatePresence mode="wait" makes sure only one of these three
        states is mounted at any time: loading skeleton, empty message,
        or the real table. When the skeleton fades out, the table slides
        in — no jarring instant-replacement flash.
        */}
        <AnimatePresence mode="wait">
          {isLoading ? (
            <motion.div
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="w-full animate-pulse"
            >
              <div className="h-12 bg-slate-50 border-b border-slate-200 flex items-center px-4 gap-4">
                {[...Array(7)].map((_, i) => (
                  <div key={i} className="h-4 bg-slate-200 rounded flex-1"></div>
                ))}
              </div>
              {[...Array(5)].map((_, row) => (
                <div key={row} className="flex items-center px-4 py-4 border-b border-slate-100 gap-4">
                  {[...Array(7)].map((_, col) => (
                    <div key={col} className={`h-4 bg-slate-100 rounded flex-1 ${col === 6 ? 'max-w-[100px]' : ''}`}></div>
                  ))}
                </div>
              ))}
            </motion.div>
          ) : orders.length === 0 ? (
            <motion.div
              key="empty"
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="p-10 text-center text-slate-500"
            >
              No purchase orders found.
            </motion.div>
          ) : (
            <motion.div
              key="table"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ type: "spring", stiffness: 260, damping: 20 }}
            >
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
                {/*
                The tbody uses rowContainerVariants so each <tr> inside
                it staggers in with a 0.05s delay after the previous one.
                "hidden" and "visible" match the variants we defined above.
                */}
                <motion.tbody
                  className="divide-y divide-slate-100"
                  variants={rowContainerVariants}
                  initial="hidden"
                  animate="visible"
                >
                  {orders.map((order, idx) => (
                    <motion.tr
                      key={order.po_id ?? idx}
                      variants={singleRowVariants}
                      className="hover:bg-slate-50 transition-colors"
                    >
                      <td className="p-4 font-mono text-sm font-medium text-indigo-600">{order.po_id}</td>
                      <td className="p-4 font-medium text-slate-700">{order.supplier_id}</td>
                      <td className="p-4 text-slate-600">{new Date(order.order_date).toLocaleDateString()}</td>
                      <td className="p-4 text-slate-600">{new Date(order.expected_delivery_date).toLocaleDateString()}</td>
                      <td className="p-4 text-slate-600 font-medium">{order.item_count} items</td>
                      <td className="p-4 font-bold text-slate-800">₹{order.total_value_rupees.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                      <td className="p-4">{getStatusBadge(order.status)}</td>
                    </motion.tr>
                  ))}
                </motion.tbody>
              </table>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
