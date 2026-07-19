"use client";

import React, { useState } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { ArrowLeft, Plus, Search } from 'lucide-react';
import Scorecard from '@/components/suppliers/Scorecard';
import { AddVendorModal } from '@/components/suppliers/AddVendorModal';

export default function SuppliersPage() {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [vendors, setVendors] = useState([
    { supplierId: "SUPP-001", label: "Elite Performance" },
    { supplierId: "SUPP-002", label: "Average Performance (SLA Warning)" },
    { supplierId: "SUPP-003", label: "Critical Risk" },
  ]);

  const filteredVendors = vendors.filter((v: any) => {
    const vendorName = (v.name || v.label || "").toLowerCase();
    const vendorId = (v.supplier_id || v.supplierId || "").toLowerCase();
    const query = (searchQuery || "").toLowerCase();
    return vendorName.includes(query) || vendorId.includes(query);
  });

  const handleVendorCreated = (newVendor: any) => {
    setVendors((prev) => [
      ...prev,
      { supplierId: newVendor.supplier_id, label: "Newly Onboarded" },
    ]);
  };

  return (
    <div className="relative min-h-screen bg-[#fdfbfb] text-slate-800 overflow-x-hidden selection:bg-blue-100 font-sans antialiased">

      {/* ETHEREAL BIOLOGICAL ORBS */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none flex items-center justify-center z-0">
        <motion.div
          animate={{ rotate: 360, scale: [1, 1.05, 1] }}
          transition={{ duration: 30, repeat: Infinity, ease: "linear" }}
          className="absolute w-[800px] h-[800px] bg-rose-100/50 blur-[120px] rounded-full will-change-transform translate-x-1/4 -translate-y-1/4 mix-blend-multiply"
        />
        <motion.div
          animate={{ rotate: -360, scale: [1, 1.1, 1] }}
          transition={{ duration: 40, repeat: Infinity, ease: "linear" }}
          className="absolute w-[600px] h-[600px] bg-blue-100/50 blur-[120px] rounded-full will-change-transform -translate-x-1/4 translate-y-1/4 mix-blend-multiply"
        />
      </div>

      <div className="relative z-10 max-w-[1600px] mx-auto p-6 md:p-10 min-h-screen flex flex-col">

        {/* HEADER WITH PREDICTIVE INTENT NAVIGATION */}
        <header className="flex justify-between items-center mb-12">
          <div className="flex items-center gap-6">
            <Link href="/pos">
              <motion.div
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                className="p-3 bg-white/60 backdrop-blur-md border border-white/80 shadow-sm rounded-2xl text-slate-500 hover:text-slate-800 hover:bg-white transition-colors flex items-center justify-center group will-change-transform"
              >
                <ArrowLeft size={24} className="group-hover:-translate-x-1 transition-transform" />
              </motion.div>
            </Link>
            <div>
              <h1 className="text-3xl font-black tracking-tight text-slate-900">Vendor Intelligence</h1>
              <p className="text-slate-500 font-medium mt-1">Real-time supply chain risk analysis</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* ZERO-LATENCY SEARCH */}
            <div className="relative group w-64">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-indigo-500 transition-colors" size={18} />
              <input
                type="text"
                placeholder="Search vendors..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2 bg-white/50 border border-white/60 rounded-xl text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-200 shadow-sm backdrop-blur-md transition-all"
              />
            </div>

            {/* ADD VENDOR BUTTON */}
            <motion.button
              onClick={() => setIsModalOpen(true)}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.95 }}
              className="flex items-center gap-2 px-5 py-2.5 bg-slate-800 hover:bg-slate-900 text-white font-medium rounded-xl shadow-md transition-all"
            >
              <Plus size={18} />
              Add Vendor
            </motion.button>
          </div>
        </header>

        {/* SPATIAL SCORECARD MATRIX */}
        <div className="flex-1 flex flex-col gap-12 items-center justify-start pb-24">
          {filteredVendors.length === 0 && (
            <div className="w-full text-center mt-20">
              <p className="text-slate-400 text-lg font-medium">No vendors match your search.</p>
            </div>
          )}
          {filteredVendors.map((v, idx) => (
            <React.Fragment key={v.supplierId}>
              {idx > 0 && (
                <div className="w-full text-center mt-8 mb-4">
                  <p className="text-sm font-bold text-slate-400 uppercase tracking-widest">{v.label}</p>
                </div>
              )}
              {idx === 0 && (
                <div className="w-full text-center mb-4">
                  <p className="text-sm font-bold text-slate-400 uppercase tracking-widest">{v.label}</p>
                </div>
              )}
              <Scorecard supplierId={v.supplierId} />
            </React.Fragment>
          ))}
        </div>

      </div>

      <AddVendorModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={handleVendorCreated}
      />
    </div>
  );
}
