"use client";

import React, { useState, useEffect } from 'react';
import ReactDOM from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Package, Calendar, CheckCircle } from 'lucide-react';
import { toast } from 'sonner';
import { api, PurchaseOrderResponse, PurchaseOrderLineItem } from '@/services/api';

interface ReceiveOrderPanelProps {
  isOpen: boolean;
  onClose: () => void;
  poId: string;
  onSuccess: () => void;
}

export const ReceiveOrderPanel: React.FC<ReceiveOrderPanelProps> = ({ isOpen, onClose, poId, onSuccess }) => {
  const [mounted, setMounted] = useState(false);
  const [poDetails, setPoDetails] = useState<PurchaseOrderResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  
  // State for the form
  const [deliveryDate, setDeliveryDate] = useState('');
  
  // State to hold the user's inputs for the newly received quantities
  // Record<sku_id, number>
  const [receiveQtys, setReceiveQtys] = useState<Record<string, number>>({});

  useEffect(() => {
    setMounted(true);
    setDeliveryDate(new Date().toISOString().split('T')[0]);
  }, []);

  useEffect(() => {
    if (!isOpen || !poId) return;
    
    let cancelled = false;
    const loadPo = async () => {
      setIsLoading(true);
      try {
        const data = await api.fetchPurchaseOrder(poId);
        if (cancelled) return;
        
        if (data) {
          setPoDetails(data);
          
          // Pre-fill defaults: remaining balance
          const defaults: Record<string, number> = {};
          data.items.forEach((item: PurchaseOrderLineItem) => {
            const remaining = Math.max(0, item.ordered_qty - item.delivered_qty);
            defaults[item.sku_id] = remaining;
          });
          setReceiveQtys(defaults);
        }
      } catch (error) {
        console.error("Failed to load PO details", error);
        toast.error("Failed to load PO details");
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    };
    
    loadPo();
    return () => { cancelled = true; };
  }, [isOpen, poId]);

  const handleQtyChange = (skuId: string, value: string, remaining: number) => {
    // Parse the value
    let parsed = parseInt(value, 10);
    if (isNaN(parsed) || parsed < 0) {
      parsed = 0;
    }
    
    // Validate against over-delivery
    if (parsed > remaining) {
      parsed = remaining;
      toast.error(`Cannot receive more than the remaining balance of ${remaining}`);
    }
    
    setReceiveQtys(prev => ({ ...prev, [skuId]: parsed }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!poDetails) return;

    // Filter out items with 0 receive qty
    const itemsToReceive = poDetails.items
      .filter((item: PurchaseOrderLineItem) => receiveQtys[item.sku_id] > 0)
      .map((item: PurchaseOrderLineItem) => ({
        sku_id: item.sku_id,
        delivered_qty: receiveQtys[item.sku_id]
      }));
      
    if (itemsToReceive.length === 0) {
      toast.error("Please specify at least one item quantity to receive.");
      return;
    }

    setIsSubmitting(true);
    try {
      await api.post('/api/v1/purchase-orders/receive', {
        po_id: poId,
        actual_delivery_date: deliveryDate,
        items: itemsToReceive
      });
      
      toast.success("Delivery recorded successfully!");
      onSuccess();
      onClose();
    } catch (error: any) {
      const msg = error?.message || "Failed to record delivery";
      console.error(msg);
      toast.error(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

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
            className="fixed right-0 top-0 bottom-0 w-full max-w-2xl bg-white shadow-2xl z-[101] border-l border-slate-200 flex flex-col"
          >
            <div className="p-6 border-b flex justify-between bg-slate-50">
              <div>
                <h2 className="text-xl font-bold flex items-center gap-2">
                  <Package className="text-indigo-600" /> Receive Delivery
                </h2>
                <p className="text-sm text-slate-500 mt-1">
                  PO ID: <span className="font-bold">{poId}</span>
                  {poDetails && ` · Vendor: ${poDetails.supplier_name}`}
                </p>
              </div>
              <button onClick={onClose} className="p-2 hover:bg-slate-200 rounded-full transition-colors">
                <X size={20} />
              </button>
            </div>

            <div className="p-6 flex-1 overflow-y-auto space-y-6 bg-slate-50/50">
              {isLoading ? (
                <div className="space-y-4">
                  <div className="h-10 bg-slate-200 rounded-lg animate-pulse w-1/3"></div>
                  <div className="h-24 bg-slate-200 rounded-xl animate-pulse"></div>
                  <div className="h-24 bg-slate-200 rounded-xl animate-pulse"></div>
                </div>
              ) : !poDetails ? (
                <div className="text-center p-10 text-slate-500">
                  Failed to load purchase order details.
                </div>
              ) : (
                <>
                  <div>
                    <label className="block text-sm font-medium mb-1 text-slate-700">Actual Delivery Date</label>
                    <div className="relative w-1/2">
                      <Calendar className="absolute left-3 top-2.5 text-slate-400" size={18} />
                      <input 
                        type="date" 
                        required 
                        value={deliveryDate} 
                        onChange={e => setDeliveryDate(e.target.value)} 
                        className="w-full pl-10 pr-4 py-2 border border-slate-200 rounded-lg outline-none focus:ring-2 focus:ring-indigo-500 shadow-sm" 
                      />
                    </div>
                  </div>

                  <div className="space-y-3">
                    <h3 className="text-sm font-bold text-slate-900">Line Items</h3>
                    {poDetails.items.map((item: PurchaseOrderLineItem) => {
                      const remaining = Math.max(0, item.ordered_qty - item.delivered_qty);
                      const isFullyDelivered = remaining === 0;

                      return (
                        <div key={item.sku_id} className={`flex gap-4 items-center bg-white border border-slate-200 rounded-xl p-4 shadow-sm ${isFullyDelivered ? 'opacity-60' : ''}`}>
                          <div className="flex-1">
                            <div className="font-bold text-slate-700">{item.sku_id}</div>
                            <div className="text-xs text-slate-500 mt-1 flex gap-3">
                              <span>Ordered: <strong>{item.ordered_qty}</strong></span>
                              <span>Delivered: <strong>{item.delivered_qty}</strong></span>
                              <span className="text-indigo-600">Remaining: <strong>{remaining}</strong></span>
                            </div>
                          </div>
                          
                          <div className="w-1/3 text-right">
                            {isFullyDelivered ? (
                              <span className="inline-flex items-center gap-1 text-green-600 text-sm font-bold bg-green-50 px-3 py-1.5 rounded-lg border border-green-100">
                                <CheckCircle size={16} /> Completed
                              </span>
                            ) : (
                              <div>
                                <label className="text-xs font-semibold text-slate-500 mb-1 block">New Delivery Qty</label>
                                <input 
                                  type="number" 
                                  min="0"
                                  max={remaining}
                                  value={receiveQtys[item.sku_id] ?? 0}
                                  onChange={e => handleQtyChange(item.sku_id, e.target.value, remaining)} 
                                  className="w-24 px-3 py-1.5 border border-slate-200 rounded-lg focus:ring-2 focus:ring-indigo-500 outline-none text-right font-medium text-slate-800" 
                                />
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </>
              )}
            </div>

            <div className="p-6 border-t bg-white space-y-3">
              <button 
                onClick={handleSubmit} 
                disabled={isSubmitting || isLoading || !poDetails} 
                className="w-full py-3 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-xl shadow-md disabled:opacity-50 transition-all flex items-center justify-center gap-2"
              >
                {isSubmitting ? (
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  <>Confirm Delivery</>
                )}
              </button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );

  if (!mounted) return null;
  return ReactDOM.createPortal(panelContent, document.body);
};
