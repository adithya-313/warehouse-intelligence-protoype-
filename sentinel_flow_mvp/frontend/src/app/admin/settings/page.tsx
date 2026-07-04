"use client";

import React from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { ArrowLeft } from 'lucide-react';
import SettingsDashboard from '@/components/admin/SettingsDashboard';

export default function SettingsPage() {
  return (
    <div className="relative min-h-screen bg-[#fdfbfb] text-slate-800 overflow-hidden selection:bg-blue-100 font-sans antialiased">
      
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
                whileHover={{ scale: 1.05, x: -5 }}
                whileTap={{ scale: 0.95 }}
                className="p-3 bg-white/60 backdrop-blur-md border border-white/80 shadow-sm rounded-2xl text-slate-500 hover:text-slate-800 hover:bg-white transition-all flex items-center justify-center group"
              >
                <ArrowLeft size={24} className="group-hover:-translate-x-1 transition-transform" />
              </motion.div>
            </Link>
            <div>
              <h1 className="text-3xl font-black tracking-tight text-slate-900">System Configuration</h1>
              <p className="text-slate-500 font-medium mt-1">Manage integrations and security</p>
            </div>
          </div>
        </header>
        
        {/* SPATIAL SETTINGS DASHBOARD */}
        <div className="flex-1 flex items-center justify-center pb-12">
          <SettingsDashboard />
        </div>

      </div>
    </div>
  );
}
