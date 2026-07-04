"use client";

import React, { useState, useEffect } from 'react';
import { motion, useMotionValue, useTransform, useSpring, AnimatePresence } from 'framer-motion';
import { MessageSquare, CreditCard, Check, Loader2, Key, Eye, EyeOff, ShieldCheck } from 'lucide-react';
import { cn } from '@/lib/utils';

const TABS = [
  { id: 'whatsapp', label: 'WhatsApp API', icon: MessageSquare },
  { id: 'payments', label: 'UPI Payments', icon: CreditCard },
];

export default function SettingsDashboard() {
  const [activeTab, setActiveTab] = useState(TABS[0].id);
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'success'>('idle');
  const [showToken, setShowToken] = useState(false);
  const [formData, setFormData] = useState({
    upi_id: '',
    meta_whatsapp_token: '',
    whatsapp_phone_id: ''
  });

  // OPTIMIZED PHYSICS: Softer springs to prevent mouse jitter
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const mouseXSpring = useSpring(x, { stiffness: 150, damping: 25 });
  const mouseYSpring = useSpring(y, { stiffness: 150, damping: 25 });
  const rotateX = useTransform(mouseYSpring, [-0.5, 0.5], ["2deg", "-2deg"]);
  const rotateY = useTransform(mouseXSpring, [-0.5, 0.5], ["-2deg", "2deg"]);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    x.set(mouseX / width - 0.5);
    y.set(mouseY / height - 0.5);
  };

  const handleMouseLeave = () => {
    x.set(0);
    y.set(0);
  };

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
    <div 
      className="w-full max-w-5xl mx-auto perspective-[2000px] z-10 relative"
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      <motion.div 
        style={{ rotateX, rotateY }}
        initial={{ opacity: 0, scale: 0.98, y: 10 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 400, damping: 40 }}
        className="relative rounded-[2.5rem] p-[1px] bg-gradient-to-br from-blue-200/60 via-rose-200/60 to-amber-200/60 shadow-[0_32px_64px_rgba(0,0,0,0.08)] will-change-transform flex flex-col md:flex-row min-h-[600px]"
      >
        {/* OPTICS FIX: Removed transformStyle and translateZ to prevent text rasterization blur */}
        <div className="relative w-full h-full bg-white/70 backdrop-blur-3xl rounded-[calc(2.5rem-1px)] flex flex-col md:flex-row overflow-hidden">
          
          <div className="absolute inset-0 opacity-[0.03] pointer-events-none mix-blend-overlay" 
               style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg viewBox=%220 0 200 200%22 xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cfilter id=%22noiseFilter%22%3E%3CfeTurbulence type=%22fractalNoise%22 baseFrequency=%220.8%22 numOctaves=%223%22 stitchTiles=%22stitch%22/%3E%3C/filter%3E%3Crect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23noiseFilter)%22/%3E%3C/svg%3E")' }}>
          </div>

          {/* Sidebar Navigation */}
          <div className="w-full md:w-72 bg-white/40 border-r border-slate-100/50 p-8 flex flex-col relative z-10">
            <div className="mb-12">
              <h2 className="text-slate-800 text-2xl font-bold tracking-tight">Settings</h2>
              <p className="text-slate-500 text-xs uppercase tracking-widest mt-2 font-semibold">Command Center</p>
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
                      "relative flex items-center gap-3 px-4 py-3.5 rounded-2xl text-sm font-bold transition-all outline-none group",
                      isActive ? "text-slate-900" : "text-slate-500 hover:text-slate-700"
                    )}
                  >
                    {isActive && (
                      <motion.div
                        layoutId="activeTab"
                        className="absolute inset-0 bg-white shadow-sm border border-slate-100 rounded-2xl"
                        transition={{ type: "spring", stiffness: 500, damping: 35 }}
                      />
                    )}
                    <Icon size={18} className={cn("relative z-10 transition-transform", isActive ? "scale-110 text-blue-600" : "group-hover:scale-110")} />
                    <span className="relative z-10">{tab.label}</span>
                  </button>
                );
              })}
            </nav>
          </div>

          {/* Content Area */}
          <div className="flex-1 p-10 md:p-12 flex flex-col relative z-10">
            {/* LAYOUT FIX: Added min-h-[350px] to prevent container snapping on tab switch */}
            <div className="min-h-[350px]">
              <AnimatePresence mode="wait">
                <motion.div
                  key={activeTab}
                  initial={{ opacity: 0, y: 10, filter: "blur(4px)" }}
                  animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
                  exit={{ opacity: 0, y: -10, filter: "blur(4px)" }}
                  transition={{ duration: 0.25, ease: "easeOut" }}
                  className="flex-1"
                >
                  {activeTab === 'whatsapp' && (
                    <div className="space-y-10">
                      <div>
                        <h3 className="text-3xl font-bold text-slate-800 tracking-tight mb-3 flex items-center gap-3">
                          WhatsApp Integration <ShieldCheck className="text-emerald-500 w-6 h-6" />
                        </h3>
                        <p className="text-slate-500 text-sm leading-relaxed max-w-md font-medium">Connect your official Meta Business account to enable automated patient adherence loops.</p>
                      </div>
                      
                      <div className="space-y-8 max-w-lg">
                        <div className="space-y-2 group">
                          <label className="text-xs font-bold text-slate-400 uppercase tracking-wider flex items-center gap-2">
                            <Key size={14} className="text-blue-500" /> Permanent Access Token
                          </label>
                          <div className="relative rounded-2xl p-[1px] bg-slate-200 transition-all duration-500 group-focus-within:bg-gradient-to-r group-focus-within:from-blue-400 group-focus-within:to-cyan-400 shadow-sm">
                            <div className="relative bg-white/90 backdrop-blur-xl rounded-[calc(2rem-1px)] flex items-center">
                              <input 
                                type={showToken ? "text" : "password"} 
                                value={formData.meta_whatsapp_token}
                                onChange={(e) => setFormData({...formData, meta_whatsapp_token: e.target.value})}
                                className="w-full bg-transparent px-5 py-4 text-slate-800 font-mono text-sm focus:outline-none placeholder-slate-300"
                                placeholder="EAAGm0..."
                              />
                              <button 
                                onClick={() => setShowToken(!showToken)}
                                className="absolute right-3 p-2 text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-xl transition-colors"
                              >
                                {showToken ? <EyeOff size={18} /> : <Eye size={18} />}
                              </button>
                            </div>
                          </div>
                        </div>

                        <div className="space-y-2 group">
                          <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Phone Number ID</label>
                          <div className="relative rounded-2xl p-[1px] bg-slate-200 transition-all duration-500 group-focus-within:bg-gradient-to-r group-focus-within:from-blue-400 group-focus-within:to-cyan-400 shadow-sm">
                            <input 
                              type="text" 
                              value={formData.whatsapp_phone_id}
                              onChange={(e) => setFormData({...formData, whatsapp_phone_id: e.target.value})}
                              className="w-full bg-white/90 backdrop-blur-xl rounded-[calc(2rem-1px)] px-5 py-4 text-slate-800 font-mono text-sm focus:outline-none placeholder-slate-300"
                              placeholder="1029384756"
                            />
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {activeTab === 'payments' && (
                    <div className="space-y-10">
                      <div>
                        <h3 className="text-3xl font-bold text-slate-800 tracking-tight mb-3">UPI Payments</h3>
                        <p className="text-slate-500 text-sm leading-relaxed max-w-md font-medium">Set the destination UPI ID. This will be dynamically embedded into patient refill reminders.</p>
                      </div>
                      <div className="space-y-2 max-w-lg group">
                        <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Business UPI ID</label>
                        <div className="relative rounded-2xl p-[1px] bg-slate-200 transition-all duration-500 group-focus-within:bg-gradient-to-r group-focus-within:from-emerald-400 group-focus-within:to-teal-400 shadow-sm">
                          <input 
                            type="text" 
                            value={formData.upi_id}
                            onChange={(e) => setFormData({...formData, upi_id: e.target.value})}
                            className="w-full bg-white/90 backdrop-blur-xl rounded-[calc(2rem-1px)] px-5 py-4 text-slate-800 font-mono text-sm focus:outline-none placeholder-slate-300"
                            placeholder="pharmacy@icici"
                          />
                        </div>
                      </div>
                    </div>
                  )}
                </motion.div>
              </AnimatePresence>
            </div>

            <div className="mt-auto pt-8 flex justify-end">
              <motion.button
                onClick={handleSave}
                disabled={saveState !== 'idle'}
                whileHover={{ scale: 1.02, backgroundPosition: "100% center" }}
                whileTap={{ scale: 0.97 }}
                className={cn(
                  "relative overflow-hidden px-8 py-4 rounded-2xl font-bold text-sm transition-all flex items-center justify-center min-w-[160px] shadow-[inset_0_1px_1px_rgba(255,255,255,0.25),0_12px_24px_rgba(15,23,42,0.15)] border border-slate-800",
                  saveState === 'idle' ? "bg-gradient-to-r from-slate-900 via-slate-700 to-slate-900 bg-[length:200%_auto] text-white" : 
                  saveState === 'saving' ? "bg-blue-500 text-white border-blue-400" : 
                  "bg-emerald-500 text-white border-emerald-400 shadow-[0_0_30px_rgba(16,185,129,0.4)]"
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
        </div>
      </motion.div>
    </div>
  );
}
