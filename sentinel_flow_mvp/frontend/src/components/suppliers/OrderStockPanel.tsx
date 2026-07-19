"use client";

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, ShoppingCart, Calendar, Package } from 'lucide-react';
import { api } from '@/services/api';

interface OrderStockPanelProps {
  isOpen: boolean;
  onClose: () => void;
  supplierId: string;
  supplierName: string;
}

export const OrderStockPanel: React.FC<OrderStockPanelProps> = ({ isOpen, onClose, supplierId, supplierName }) => {
  const [sku, setSku] = useState('');
  const [qty, setQty] = useState('');
  const [cost, setCost] = useState('');
  const [mrp, setMrp] = useState('');
  const [deliveryDate, setDeliveryDate] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    try {
      await api.post('/api/v1/purchase-orders', {
        supplier_id: supplierId,
        sku_id: sku,
        ordered_qty: parseInt(qty),
        cost_price: parseFloat(cost),
        expected_mrp: parseFloat(mrp),
        expected_delivery_date: deliveryDate
      });
      setSku(''); setQty(''); setCost(''); setMrp(''); setDeliveryDate('');
      onClose();
    } catch (error) {
      console.error("Failed to submit PO", error);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
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
            className="fixed right-0 top-0 bottom-0 w-full max-w-md bg-white shadow-2xl z-[101] border-l border-slate-200 overflow-y-auto flex flex-col"
          >
            <div className="p-6 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
              <div>
                <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2">
                  <ShoppingCart size={20} className="text-indigo-600" /> New Purchase Order
                </h2>
                <p className="text-sm text-slate-500 mt-1">Ordering from <span className="font-semibold text-slate-700">{supplierName}</span></p>
              </div>
              <button onClick={onClose} className="p-2 hover:bg-slate-200 rounded-full transition-colors"><X size={20} /></button>
            </div>

            <form onSubmit={handleSubmit} className="p-6 flex-1 flex flex-col gap-5">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Target SKU</label>
                <div className="relative">
                  <Package className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
                  <input type="text" required value={sku} onChange={e => setSku(e.target.value)} placeholder="e.g. AMOX500" className="w-full pl-10 pr-4 py-2 border rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none" />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Quantity</label>
                  <input type="number" required min="1" value={qty} onChange={e => setQty(e.target.value)} placeholder="Units" className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Expected Delivery</label>
                  <div className="relative">
                    <Calendar className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
                    <input type="date" required min={new Date().toISOString().split('T')[0]} value={deliveryDate} onChange={e => setDeliveryDate(e.target.value)} className="w-full pl-10 pr-4 py-2 border rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none" />
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Unit Cost (₹)</label>
                  <input type="number" required min="0.1" step="0.01" value={cost} onChange={e => setCost(e.target.value)} placeholder="0.00" className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1">Expected MRP (₹)</label>
                  <input type="number" required min="0.1" step="0.01" value={mrp} onChange={e => setMrp(e.target.value)} placeholder="0.00" className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none" />
                </div>
              </div>

              <div className="mt-auto pt-6">
                <button type="submit" disabled={isSubmitting} className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-medium rounded-xl shadow-sm transition-all disabled:opacity-50">
                  {isSubmitting ? "Transmitting Order..." : "Submit Purchase Order"}
                </button>
              </div>
            </form>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
};
