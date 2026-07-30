"use client";

import React, { useState, useEffect } from 'react';
import ReactDOM from 'react-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Building2, Mail } from 'lucide-react';
import { api } from '@/services/api';

interface AddVendorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (newVendor: any) => void;
}

export const AddVendorModal: React.FC<AddVendorModalProps> = ({ isOpen, onClose, onSuccess }) => {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !email) return;

    setIsSubmitting(true);
    try {
      const response = await api.post('/api/v1/suppliers', {
        name,
        contact_email: email,
        industry_vertical: "PHARMACEUTICALS"
      });
      onSuccess(response);
      setName('');
      setEmail('');
      onClose();
    } catch (error) {
      console.error("Failed to onboard vendor", error);
    } finally {
      setIsSubmitting(false);
    }
  };

  const modalContent = (
    <AnimatePresence mode="wait">
      {isOpen && (
        <motion.div
          key="vendor-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1, transition: { duration: 0.3 } }}
          exit={{ opacity: 0, transition: { duration: 0.2 } }}
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/10 backdrop-blur-md p-4 transform-gpu"
        >
          <motion.div
            key="vendor-modal"
            initial={{ opacity: 0, scale: 0.95, y: 15 }}
            animate={{ opacity: 1, scale: 1, y: 0, transition: { type: "spring", damping: 30, stiffness: 300 } }}
            exit={{ opacity: 0, scale: 0.95, y: 10 }}
            className="w-full max-w-lg rounded-3xl shadow-2xl overflow-hidden bg-white/70 backdrop-blur-2xl border border-white/80"
          >
            <div className="flex justify-between items-center p-6 border-b border-gray-200/50 bg-white/40">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-gradient-to-br from-blue-100 to-indigo-100 rounded-xl border border-white shadow-sm">
                  <Building2 className="text-indigo-500" size={24} />
                </div>
                <h2 className="text-xl font-semibold text-slate-800">Onboard Supplier</h2>
              </div>
              <button onClick={onClose} className="text-slate-400 hover:text-slate-700 transition-colors">
                <X size={24} />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-6 space-y-6">
              <div className="space-y-4">
                <div className="relative">
                  <Building2 className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
                  <input
                    type="text"
                    placeholder="Registered Vendor Name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    required
                    className="w-full pl-12 pr-4 py-3 bg-white/50 border border-white/60 rounded-xl text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-200 shadow-sm"
                  />
                </div>
                <div className="relative">
                  <Mail className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
                  <input
                    type="email"
                    placeholder="Primary Contact Email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    className="w-full pl-12 pr-4 py-3 bg-white/50 border border-white/60 rounded-xl text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-200 shadow-sm"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full py-3 px-4 bg-slate-800 hover:bg-slate-900 text-white font-medium rounded-xl shadow-md transition-all active:scale-95 disabled:opacity-50 disabled:active:scale-100 flex justify-center items-center gap-2"
              >
                {isSubmitting ? (
                  <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                ) : (
                  "Initialize Vendor Ledger"
                )}
              </button>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );

  // A React Portal renders this component directly into document.body instead of its inline DOM location.
  // We need this to escape the `will-change` CSS property on our root template.tsx, which traps fixed-position elements.
  // The mounted check is required because document.body doesn't exist during Next.js SSR.
  if (!mounted) return null;
  return ReactDOM.createPortal(modalContent, document.body);
};
