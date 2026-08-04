"use client";

import React, { useEffect, useState } from 'react';
import { motion, AnimatePresence, type Variants } from 'framer-motion';
import { Package, Clock, CheckCircle, AlertTriangle, PackageCheck } from 'lucide-react';
import { api } from '@/services/api';
import BackButton from '@/components/ui/BackButton';
import { ReceiveOrderPanel } from '@/components/orders/ReceiveOrderPanel';
import { calculateDaysLate } from '@/utils/orderDelay';

export default function OrderLedgerPage() {
  const [orders, setOrders] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  
  const [isReceivePanelOpen, setIsReceivePanelOpen] = useState(false);
  const [selectedPoId, setSelectedPoId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const fetchOrders = async () => {
      setIsLoading(true);
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
  }, [refreshKey]);

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
        or the real table. When the skeleton fades out, the table fades
        in — no jarring instant-replacement flash.
        */}
        <AnimatePresence mode="wait">
          {isLoading ? (
            // This "loading" table looks almost exactly like the real table below,
            // except every cell shows a gray pulsing bar instead of real data.
            // We use the SAME table-fixed layout and SAME column widths so that
            // when the real data arrives, the table doesn't suddenly resize or
            // reshape — it already has the right shape, just with placeholder content.
            <motion.div
              key="loading"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              <table className="w-full table-fixed text-left border-collapse">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200 text-sm font-semibold text-slate-600">
                    <th className="p-4 w-[14%]">PO ID</th>
                    <th className="p-4 w-[14%]">Vendor ID</th>
                    <th className="p-4 w-[16%]">Order Date</th>
                    <th className="p-4 w-[16%]">Expected Delivery</th>
                    <th className="p-4 w-[12%]">Line Items</th>
                    <th className="p-4 w-[16%]">Capital Value</th>
                    <th className="p-4 w-[12%]">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {[1, 2, 3, 4, 5].map((rowNum) => (
                    <tr key={rowNum} className="border-b border-slate-100">
                      <td className="p-4"><div className="h-4 bg-slate-200 rounded animate-pulse"></div></td>
                      <td className="p-4"><div className="h-4 bg-slate-200 rounded animate-pulse"></div></td>
                      <td className="p-4"><div className="h-4 bg-slate-200 rounded animate-pulse"></div></td>
                      <td className="p-4"><div className="h-4 bg-slate-200 rounded animate-pulse"></div></td>
                      <td className="p-4"><div className="h-4 bg-slate-200 rounded animate-pulse"></div></td>
                      <td className="p-4"><div className="h-4 bg-slate-200 rounded animate-pulse"></div></td>
                      <td className="p-4"><div className="h-4 bg-slate-200 rounded animate-pulse"></div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
            // This wrapper used to slide up AND fade in. The page itself (template.tsx) already
            // slides up when you navigate here, and each row below already slides up when it
            // appears. Having three things slide at once made everything look like it was
            // jittering. This wrapper now only fades in — the sliding motion is handled once,
            // by the rows, so it reads as one smooth reveal instead of three fighting animations.
            <motion.div
              key="table"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
            >
              {/*
              Giving every column a fixed width — instead of letting the browser
              guess based on content — means the table looks exactly the same
              whether it's showing placeholder bars or real order data. Nothing
              needs to resize when the data swaps in.
              */}
              <table className="w-full table-fixed text-left border-collapse">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200 text-sm font-semibold text-slate-600">
                    <th className="p-4 w-[14%]">PO ID</th>
                    <th className="p-4 w-[14%]">Vendor</th>
                    <th className="p-4 w-[16%]">Order Date</th>
                    <th className="p-4 w-[16%]">Expected Delivery</th>
                    <th className="p-4 w-[12%]">Line Items</th>
                    <th className="p-4 w-[16%]">Capital Value</th>
                    <th className="p-4 w-[12%]">Status</th>
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
                  {orders.map((order, idx) => {
                    const daysLate = calculateDaysLate(order.status, order.expected_delivery_date, order.actual_delivery_date);
                    
                    const getDelayBadge = (daysLate: number) => {
                      if (daysLate <= 0) return null;
                      if (daysLate >= 7) {
                        return <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-red-100 text-red-700 font-bold border border-red-200">• {daysLate} days late</span>;
                      } else if (daysLate >= 3) {
                        return <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-red-50 text-red-600 font-medium border border-red-100">• {daysLate} days late</span>;
                      } else {
                        return <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-orange-50 text-orange-600 font-medium border border-orange-100">• {daysLate} {daysLate === 1 ? 'day' : 'days'} late</span>;
                      }
                    };

                    return (
                      <motion.tr
                        key={order.po_id ?? idx}
                        variants={singleRowVariants}
                        className="hover:bg-slate-50 transition-colors"
                      >
                      <td className="p-4 font-mono text-sm font-medium text-indigo-600">{order.po_id}</td>
                      <td className="p-4 font-medium text-slate-700">{order.supplier_name}</td>
                      <td className="p-4 text-slate-600">{new Date(order.order_date).toLocaleDateString()}</td>
                      <td className="p-4 text-slate-600">{new Date(order.expected_delivery_date).toLocaleDateString()}</td>
                      <td className="p-4 text-slate-600 font-medium">{order.item_count} items</td>
                      <td className="p-4 font-bold text-slate-800">₹{order.total_value_rupees.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
                      <td className="p-4">
                        <div className="flex items-center gap-3">
                          {getStatusBadge(order.status)}
                          {getDelayBadge(daysLate)}
                          {(order.status === 'SUBMITTED' || order.status === 'PARTIAL') && (
                            <button
                              onClick={() => {
                                setSelectedPoId(order.po_id);
                                setIsReceivePanelOpen(true);
                              }}
                              className="p-1.5 text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
                              title="Receive Items"
                            >
                              <PackageCheck size={18} />
                            </button>
                          )}
                        </div>
                      </td>
                    </motion.tr>
                  ))}
                </motion.tbody>
              </table>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      
      <ReceiveOrderPanel 
        isOpen={isReceivePanelOpen} 
        onClose={() => setIsReceivePanelOpen(false)} 
        poId={selectedPoId || ''} 
        onSuccess={() => setRefreshKey(prev => prev + 1)} 
      />
    </div>
  );
}
