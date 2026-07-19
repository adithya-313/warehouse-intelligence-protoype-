"use client";

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, ShoppingCart, Calendar, Search, Trash2 } from 'lucide-react';
import { api } from '@/services/api';

interface LineItem {
  id: string;
  sku_id: string;
  qty: number | '';
  cost: number | '';
  mrp: number | '';
}

export const OrderStockPanel: React.FC<any> = ({ isOpen, onClose, supplierId, supplierName }) => {
  const [deliveryDate, setDeliveryDate] = useState('');
  const [items, setItems] = useState<LineItem[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [suggestions, setSuggestions] = useState<any[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    if (searchQuery.length < 2) {
      setSuggestions([]);
      return;
    }
    const fetchCatalog = async () => {
      try {
        const res = await api.get(`/api/v1/purchase-orders/catalog/search?q=${searchQuery}`);
        setSuggestions(res);
      } catch (e) { console.error(e); }
    };
    const timeoutId = setTimeout(fetchCatalog, 300);
    return () => clearTimeout(timeoutId);
  }, [searchQuery]);

  const addItemToCart = (sku: string) => {
    if (items.find(i => i.sku_id === sku)) return;
    setItems([...items, { id: Math.random().toString(), sku_id: sku, qty: '' as any, cost: '' as any, mrp: '' as any }]);
    setSearchQuery('');
    setSuggestions([]);
  };

  const updateItem = (id: string, field: keyof LineItem, value: number | '') => {
    setItems(items.map(item => item.id === id ? { ...item, [field]: value } : item));
  };

  const removeItem = (id: string) => {
    setItems(items.filter(item => item.id !== id));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (items.length === 0) return alert("Add at least one item");

    const hasEmptyFields = items.some(i => i.qty === '' || i.cost === '' || i.mrp === '');
    if (hasEmptyFields) return alert("Please fill out all Quantity, Cost, and MRP fields.");

    setIsSubmitting(true);
    try {
      await api.post('/api/v1/purchase-orders', {
        supplier_id: supplierId,
        expected_delivery_date: deliveryDate,
        items: items.map(i => ({
          sku_id: i.sku_id,
          ordered_qty: Number(i.qty),
          cost_price: Number(i.cost),
          expected_mrp: Number(i.mrp),
        })),
      });
      setItems([]);
      setDeliveryDate('');
      onClose();
      alert("Purchase Order Successfully Transmitted!");
    } catch (error: any) {
      console.error("Failed to submit Bulk PO", error);
      alert("Failed to submit order. Check console for validation errors.");
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
            className="fixed right-0 top-0 bottom-0 w-full max-w-2xl bg-white shadow-2xl z-[101] border-l border-slate-200 flex flex-col"
          >
            <div className="p-6 border-b flex justify-between bg-slate-50">
              <div>
                <h2 className="text-xl font-bold flex items-center gap-2"><ShoppingCart className="text-indigo-600" /> Manifest Builder</h2>
                <p className="text-sm text-slate-500 mt-1">Vendor: <span className="font-bold">{supplierName}</span></p>
              </div>
              <button onClick={onClose} className="p-2 hover:bg-slate-200 rounded-full"><X size={20} /></button>
            </div>

            <div className="p-6 flex-1 overflow-y-auto space-y-6">
              <div>
                <label className="block text-sm font-medium mb-1">Expected Manifest Delivery Date</label>
                <div className="relative w-1/2">
                  <Calendar className="absolute left-3 top-2.5 text-slate-400" size={18} />
                  <input type="date" required min={new Date().toISOString().split('T')[0]} value={deliveryDate} onChange={e => setDeliveryDate(e.target.value)} className="w-full pl-10 pr-4 py-2 border rounded-lg outline-none focus:ring-2 focus:ring-indigo-500" />
                </div>
              </div>

              <div className="relative">
                <label className="block text-sm font-medium mb-1">Add Medication to Manifest</label>
                <div className="relative">
                  <Search className="absolute left-3 top-2.5 text-slate-400" size={18} />
                  <input type="text" placeholder="Type medicine name or SKU (e.g., 'amo')" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} className="w-full pl-10 pr-4 py-2 border rounded-lg outline-none focus:ring-2 focus:ring-indigo-500" />
                </div>
                {suggestions.length > 0 && (
                  <div className="absolute w-full mt-1 bg-white border rounded-lg shadow-lg z-50">
                    {suggestions.map((s: any, idx: number) => (
                      <div key={idx} onClick={() => addItemToCart(s.sku_id)} className="px-4 py-3 hover:bg-indigo-50 cursor-pointer flex justify-between items-center border-b last:border-0">
                        <span className="font-medium">{s.name}</span>
                        <span className="text-xs bg-slate-100 text-slate-600 px-2 py-1 rounded">{s.sku_id}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="space-y-3 mt-4">
                {items.length === 0 ? (
                  <div className="text-center py-10 bg-slate-50 border border-dashed rounded-xl text-slate-400">Search above to add items to this order.</div>
                ) : (
                  items.map((item) => (
                    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} key={item.id} className="flex gap-4 items-center bg-white border rounded-xl p-4 shadow-sm">
                      <div className="w-1/4 font-bold text-slate-700">{item.sku_id}</div>
                      <div className="w-1/4">
                        <label className="text-xs text-slate-500 mb-1 block">Qty</label>
                        <input type="number" min="1" value={item.qty} onChange={e => updateItem(item.id, 'qty', parseInt(e.target.value) || '')} className="w-full px-2 py-1 border rounded focus:ring-1 outline-none" />
                      </div>
                      <div className="w-1/4">
                        <label className="text-xs text-slate-500 mb-1 block">Cost (₹)</label>
                        <input type="number" min="0.1" step="0.1" value={item.cost} onChange={e => updateItem(item.id, 'cost', parseFloat(e.target.value) || '')} className="w-full px-2 py-1 border rounded focus:ring-1 outline-none" />
                      </div>
                      <div className="w-1/4">
                        <label className="text-xs text-slate-500 mb-1 block">MRP (₹)</label>
                        <input type="number" min="0.1" step="0.1" value={item.mrp} onChange={e => updateItem(item.id, 'mrp', parseFloat(e.target.value) || '')} className="w-full px-2 py-1 border rounded focus:ring-1 outline-none" />
                      </div>
                      <button onClick={() => removeItem(item.id)} className="text-red-400 hover:text-red-600 mt-5"><Trash2 size={18} /></button>
                    </motion.div>
                  ))
                )}
              </div>
            </div>

            <div className="p-6 border-t bg-slate-50">
              <button onClick={handleSubmit} disabled={isSubmitting || items.length === 0 || !deliveryDate} className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-xl disabled:opacity-50 transition-all">
                {isSubmitting ? "Generating Manifest..." : `Submit Order (${items.length} Items)`}
              </button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
};
