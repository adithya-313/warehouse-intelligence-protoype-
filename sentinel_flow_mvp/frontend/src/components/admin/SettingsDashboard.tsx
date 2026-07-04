"use client";

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, CreditCard, Check, Loader2, Key } from 'lucide-react';
import { cn } from '@/lib/utils';

const TABS = [
  { id: 'whatsapp', label: 'WhatsApp API', icon: MessageSquare },
  { id: 'payments', label: 'UPI Payments', icon: CreditCard },
];

export default function SettingsDashboard() {
  const [activeTab, setActiveTab] = useState(TABS[0].id);
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'success'>('idle');
  const [formData, setFormData] = useState({
    upi_id: '',
    meta_whatsapp_token: '',
    whatsapp_phone_id: ''
  });

  useEffect(() => {
    fetch('/api/v1/settings', { headers: { 'X-Tenant-ID': 'PHARM-001' } })
      .then(res => res.json())
      .then(data => {
        if (data.tenant_id) {
          setFormData({
            upi_id: data.upi_id || '',
            meta_whatsapp_token: data.meta_whatsapp_token_configured ? '••••••••••••••••••••••••' : '',
            whatsapp_phone_id: data.whatsapp_phone_id || ''
          });
        }
      });
  }, []);

  const handleSave = async () => {
    setSaveState('saving');
    const payload: any = { upi_id: formData.upi_id, whatsapp_phone_id: formData.whatsapp_phone_id };
    if (!formData.meta_whatsapp_token.includes('••••')) {
      payload.meta_whatsapp_token = formData.meta_whatsapp_token;
    }

    try {
      await fetch('/api/v1/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-Tenant-ID': 'PHARM-001' },
        body: JSON.stringify(payload)
      });
      setSaveState('success');
      setTimeout(() => setSaveState('idle'), 2000);
    } catch (error) {
      setSaveState('idle');
    }
  };

  return (
    <div className="relative min-h-screen bg-[#05050A] flex items-center justify-center p-6 overflow-hidden font-sans selection:bg-cyan-500/30">
      
      {/* GPU-ACCELERATED AMBIENT ORBS (Neural Aurora) */}
      {/* We use 'will-change-transform' and only animate rotation/scale to guarantee 60FPS on low-end devices */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none flex items-center justify-center">
        <motion.div 
          animate={{ rotate: 360, scale: [1, 1.1, 1] }} 
          transition={{ duration: 20, repeat: Infinity, ease: "linear" }}
          className="absolute w-[600px] h-[600px] bg-cyan-500/10 blur-[120px] rounded-full will-change-transform translate-x-1/4 -translate-y-1/4" 
        />
        <motion.div 
          animate={{ rotate: -360, scale: [1, 1.2, 1] }} 
          transition={{ duration: 25, repeat: Infinity, ease: "linear" }}
          className="absolute w-[500px] h-[500px] bg-fuchsia-500/10 blur-[120px] rounded-full will-change-transform -translate-x-1/4 translate-y-1/4" 
        />
        <motion.div 
          animate={{ scale: [1, 1.3, 1], opacity: [0.3, 0.5, 0.3] }} 
          transition={{ duration: 15, repeat: Infinity, ease: "easeInOut" }}
          className="absolute w-[400px] h-[400px] bg-amber-500/10 blur-[100px] rounded-full will-change-transform" 
        />
      </div>

      {/* QUANTUM GLASS PANEL */}
      <motion.div 
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 300, damping: 30 }}
        className="relative w-full max-w-4xl bg-white/[0.02] backdrop-blur-[80px] border border-white/[0.08] shadow-[0_0_40px_rgba(0,0,0,0.3)] rounded-[2rem] overflow-hidden flex flex-col md:flex-row min-h-[600px] z-10"
      >
        {/* Sidebar Navigation */}
        <div className="w-full md:w-72 bg-black/20 border-r border-white/[0.05] p-8 flex flex-col">
          <div className="mb-12">
            <h2 className="text-white text-2xl font-semibold tracking-tight">Settings</h2>
            <p className="text-slate-400 text-xs uppercase tracking-widest mt-2 font-medium">Pharmacy Profile</p>
          </div>

          <nav className="flex flex-col gap-2">
            {TABS.map((tab) => {
              const isActive = activeTab === tab.id;
              const Icon = tab.icon;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    "relative flex items-center gap-3 px-4 py-3.5 rounded-2xl text-sm font-medium transition-all outline-none",
                    isActive ? "text-white" : "text-slate-500 hover:text-slate-300"
                  )}
                >
                  {isActive && (
                    <motion.div
                      layoutId="activeTab"
                      className="absolute inset-0 bg-white/[0.05] border border-white/[0.1] rounded-2xl shadow-[inset_0_0_20px_rgba(255,255,255,0.02)]"
                      transition={{ type: "spring", stiffness: 400, damping: 35 }}
                    />
                  )}
                  <Icon size={18} className="relative z-10" />
                  <span className="relative z-10">{tab.label}</span>
                </button>
              );
            })}
          </nav>
        </div>

        {/* Content Area */}
        <div className="flex-1 p-10 md:p-12 flex flex-col relative">
          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.2 }}
              className="flex-1"
            >
              {activeTab === 'whatsapp' && (
                <div className="space-y-10">
                  <div>
                    <h3 className="text-3xl font-semibold text-white tracking-tight mb-3">WhatsApp Integration</h3>
                    <p className="text-slate-400 text-sm leading-relaxed max-w-md">Connect your official Meta Business account to enable automated patient adherence loops.</p>
                  </div>
                  
                  <div className="space-y-6 max-w-lg">
                    <div className="space-y-2">
                      <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider flex items-center gap-2">
                        <Key size={12} className="text-cyan-400" /> Permanent Access Token
                      </label>
                      <input 
                        type="password" 
                        value={formData.meta_whatsapp_token}
                        onChange={(e) => setFormData({...formData, meta_whatsapp_token: e.target.value})}
                        className="w-full bg-white/[0.03] border border-white/[0.1] rounded-2xl px-5 py-4 text-white font-mono text-sm focus:outline-none focus:bg-white/[0.05] focus:border-cyan-400/50 focus:ring-1 focus:ring-cyan-400/50 transition-all placeholder-white/20 shadow-inner"
                        placeholder="EAAGm0..."
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Phone Number ID</label>
                      <input 
                        type="text" 
                        value={formData.whatsapp_phone_id}
                        onChange={(e) => setFormData({...formData, whatsapp_phone_id: e.target.value})}
                        className="w-full bg-white/[0.03] border border-white/[0.1] rounded-2xl px-5 py-4 text-white font-mono text-sm focus:outline-none focus:bg-white/[0.05] focus:border-cyan-400/50 focus:ring-1 focus:ring-cyan-400/50 transition-all placeholder-white/20 shadow-inner"
                        placeholder="1029384756"
                      />
                    </div>
                  </div>
                </div>
              )}

              {activeTab === 'payments' && (
                <div className="space-y-10">
                  <div>
                    <h3 className="text-3xl font-semibold text-white tracking-tight mb-3">UPI Payments</h3>
                    <p className="text-slate-400 text-sm leading-relaxed max-w-md">Set the destination UPI ID. This will be dynamically embedded into patient refill reminders.</p>
                  </div>
                  <div className="space-y-2 max-w-lg">
                    <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Business UPI ID</label>
                    <input 
                      type="text" 
                      value={formData.upi_id}
                      onChange={(e) => setFormData({...formData, upi_id: e.target.value})}
                      className="w-full bg-white/[0.03] border border-white/[0.1] rounded-2xl px-5 py-4 text-white font-mono text-sm focus:outline-none focus:bg-white/[0.05] focus:border-cyan-400/50 focus:ring-1 focus:ring-cyan-400/50 transition-all placeholder-white/20 shadow-inner"
                      placeholder="pharmacy@icici"
                    />
                  </div>
                </div>
              )}
            </motion.div>
          </AnimatePresence>

          {/* Haptic Liquid Button */}
          <div className="mt-auto pt-8 flex justify-end">
            <motion.button
              onClick={handleSave}
              disabled={saveState !== 'idle'}
              whileHover={{ scale: 1.02 }}
              whileTap={{ scale: 0.95 }}
              className={cn(
                "relative overflow-hidden px-8 py-3.5 rounded-2xl font-semibold text-sm transition-all flex items-center justify-center min-w-[140px] shadow-lg border",
                saveState === 'idle' ? "bg-white/10 text-white border-white/20 hover:bg-white/20 hover:border-white/30" : 
                saveState === 'saving' ? "bg-cyan-500/20 text-cyan-400 border-cyan-500/50" : 
                "bg-emerald-500/20 text-emerald-400 border-emerald-500/50"
              )}
            >
              <AnimatePresence mode="wait">
                {saveState === 'idle' && <motion.span key="idle" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>Save Configuration</motion.span>}
                {saveState === 'saving' && <motion.div key="saving" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}><Loader2 className="w-5 h-5 animate-spin" /></motion.div>}
                {saveState === 'success' && <motion.div key="success" initial={{ scale: 0 }} animate={{ scale: 1 }} exit={{ scale: 0 }}><Check className="w-5 h-5" /></motion.div>}
              </AnimatePresence>
            </motion.button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
