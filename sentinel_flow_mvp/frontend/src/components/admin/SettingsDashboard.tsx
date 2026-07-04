"use client";

import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, CreditCard, Shield, Check, Loader2, Key } from 'lucide-react';
import { cn } from '@/lib/utils';

const TABS = [
  { id: 'whatsapp', label: 'WhatsApp API', icon: MessageSquare },
  { id: 'payments', label: 'UPI Payments', icon: CreditCard },
  { id: 'security', label: 'Security', icon: Shield },
];

export default function SettingsDashboard() {
  const [activeTab, setActiveTab] = useState(TABS[0].id);
  const [saveState, setSaveState] = useState<'idle' | 'saving' | 'success'>('idle');
  const [formData, setFormData] = useState({
    upi_id: '',
    meta_whatsapp_token: '',
    whatsapp_phone_id: ''
  });

  // Fetch current settings on mount
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
      })
      .catch(() => {/* backend may not be running in dev */});
  }, []);

  const handleSave = async () => {
    setSaveState('saving');
    
    // Only send token if it was actually changed (not the masked dots)
    const payload: Record<string, string> = {
      upi_id: formData.upi_id,
      whatsapp_phone_id: formData.whatsapp_phone_id,
    };
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
    } catch {
      setSaveState('idle');
    }
  };

  return (
    <div className="relative min-h-screen bg-[#030712] flex items-center justify-center p-6 overflow-hidden font-sans">
      {/* Ambient Bioluminescence Background */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[600px] bg-indigo-600/20 blur-[120px] rounded-full pointer-events-none" />
      <div className="absolute top-1/3 left-1/3 w-[400px] h-[400px] bg-cyan-500/10 blur-[100px] rounded-full pointer-events-none" />

      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 300, damping: 30 }}
        className="relative w-full max-w-4xl bg-white/[0.02] border border-white/[0.05] backdrop-blur-3xl rounded-3xl shadow-2xl overflow-hidden flex flex-col md:flex-row min-h-[600px]"
      >
        {/* Sidebar Navigation */}
        <div className="w-full md:w-72 bg-black/40 border-r border-white/[0.05] p-6 flex flex-col">
          <div className="mb-10">
            <h2 className="text-white text-xl font-black tracking-tight">Workspace</h2>
            <p className="text-gray-500 text-xs uppercase tracking-widest mt-1 font-semibold">Tenant Configuration</p>
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
                    "relative flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-colors outline-none text-left",
                    isActive ? "text-white" : "text-gray-400 hover:text-gray-200"
                  )}
                >
                  {isActive && (
                    <motion.div
                      layoutId="activeTab"
                      className="absolute inset-0 bg-indigo-500/20 border border-indigo-500/30 rounded-xl"
                      transition={{ type: "spring", stiffness: 400, damping: 30 }}
                    />
                  )}
                  <Icon size={18} className="relative z-10 flex-shrink-0" />
                  <span className="relative z-10">{tab.label}</span>
                </button>
              );
            })}
          </nav>

          {/* Sidebar Footer */}
          <div className="mt-auto pt-6 border-t border-white/[0.05]">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-full bg-indigo-500/30 border border-indigo-400/30 flex items-center justify-center">
                <span className="text-indigo-300 text-xs font-bold">P1</span>
              </div>
              <div>
                <p className="text-white text-xs font-semibold">PHARM-001</p>
                <p className="text-gray-500 text-xs">Admin</p>
              </div>
            </div>
          </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 p-10 flex flex-col relative">
          <AnimatePresence mode="wait">
            <motion.div
              key={activeTab}
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.2 }}
              className="flex-1"
            >
              {activeTab === 'whatsapp' && (
                <div className="space-y-8">
                  <div>
                    <h3 className="text-2xl font-bold text-white mb-2">Meta Graph API</h3>
                    <p className="text-gray-400 text-sm leading-relaxed">
                      Configure your official WhatsApp Business credentials for automated adherence loops.
                    </p>
                  </div>

                  <div className="space-y-5">
                    <div className="space-y-2">
                      <label className="text-xs font-bold text-gray-400 uppercase tracking-wider flex items-center gap-2">
                        <Key size={12} /> Permanent Access Token
                      </label>
                      <input
                        type="password"
                        value={formData.meta_whatsapp_token}
                        onChange={(e) => setFormData({ ...formData, meta_whatsapp_token: e.target.value })}
                        className="w-full bg-black/50 border border-white/10 rounded-xl px-4 py-3 text-white font-mono text-sm focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all placeholder-gray-700"
                        placeholder="EAAGm0..."
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-xs font-bold text-gray-400 uppercase tracking-wider">Phone Number ID</label>
                      <input
                        type="text"
                        value={formData.whatsapp_phone_id}
                        onChange={(e) => setFormData({ ...formData, whatsapp_phone_id: e.target.value })}
                        className="w-full bg-black/50 border border-white/10 rounded-xl px-4 py-3 text-white font-mono text-sm focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all placeholder-gray-700"
                        placeholder="1029384756"
                      />
                    </div>
                  </div>

                  {/* Info card */}
                  <div className="bg-indigo-500/5 border border-indigo-500/20 rounded-xl p-4">
                    <p className="text-indigo-300 text-xs leading-relaxed">
                      🔒 Your access token is encrypted at rest and never exposed via the API. The dashboard only shows whether a token is configured.
                    </p>
                  </div>
                </div>
              )}

              {activeTab === 'payments' && (
                <div className="space-y-8">
                  <div>
                    <h3 className="text-2xl font-bold text-white mb-2">UPI Integration</h3>
                    <p className="text-gray-400 text-sm leading-relaxed">
                      Set the destination UPI ID for automated refill payment links sent via WhatsApp.
                    </p>
                  </div>
                  <div className="space-y-2">
                    <label className="text-xs font-bold text-gray-400 uppercase tracking-wider">Business UPI ID</label>
                    <input
                      type="text"
                      value={formData.upi_id}
                      onChange={(e) => setFormData({ ...formData, upi_id: e.target.value })}
                      className="w-full bg-black/50 border border-white/10 rounded-xl px-4 py-3 text-white font-mono text-sm focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all placeholder-gray-700"
                      placeholder="pharmacy@icici"
                    />
                  </div>
                  <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-xl p-4">
                    <p className="text-emerald-300 text-xs leading-relaxed">
                      💳 Payment links are generated dynamically per transaction and include the patient's prescription total.
                    </p>
                  </div>
                </div>
              )}

              {activeTab === 'security' && (
                <div className="space-y-8">
                  <div>
                    <h3 className="text-2xl font-bold text-white mb-2">Security</h3>
                    <p className="text-gray-400 text-sm leading-relaxed">
                      Tenant isolation and access control configuration.
                    </p>
                  </div>
                  <div className="space-y-4">
                    {[
                      { label: 'Multi-tenant isolation', status: 'Enforced', color: 'emerald' },
                      { label: 'X-Tenant-ID header auth', status: 'Active', color: 'emerald' },
                      { label: 'Payload tenant override', status: 'Blocked', color: 'emerald' },
                      { label: 'Token encryption at rest', status: 'AES-256', color: 'indigo' },
                    ].map((item) => (
                      <div key={item.label} className="flex items-center justify-between bg-black/30 border border-white/[0.05] rounded-xl px-4 py-3">
                        <span className="text-gray-300 text-sm">{item.label}</span>
                        <span className={`text-xs font-bold px-2 py-1 rounded-md bg-${item.color}-500/10 text-${item.color}-400 border border-${item.color}-500/20`}>
                          {item.status}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </motion.div>
          </AnimatePresence>

          {/* Haptic Save Button */}
          <div className="mt-auto pt-8 border-t border-white/10 flex justify-end">
            <motion.button
              onClick={handleSave}
              disabled={saveState !== 'idle' || activeTab === 'security'}
              whileHover={{ scale: saveState === 'idle' && activeTab !== 'security' ? 1.02 : 1 }}
              whileTap={{ scale: saveState === 'idle' && activeTab !== 'security' ? 0.95 : 1 }}
              className={cn(
                "relative overflow-hidden px-8 py-3 rounded-xl font-bold text-sm transition-all flex items-center justify-center min-w-[140px]",
                activeTab === 'security'
                  ? "bg-white/5 text-gray-600 cursor-not-allowed border border-white/5"
                  : saveState === 'idle'
                  ? "bg-white text-black hover:bg-gray-200"
                  : saveState === 'saving'
                  ? "bg-indigo-600 text-white"
                  : "bg-green-500 text-white"
              )}
            >
              <AnimatePresence mode="wait">
                {saveState === 'idle' && (
                  <motion.span key="idle" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }}>
                    {activeTab === 'security' ? 'Read Only' : 'Save Changes'}
                  </motion.span>
                )}
                {saveState === 'saving' && (
                  <motion.div key="saving" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                    <Loader2 className="w-5 h-5 animate-spin" />
                  </motion.div>
                )}
                {saveState === 'success' && (
                  <motion.div key="success" initial={{ scale: 0 }} animate={{ scale: 1 }} exit={{ scale: 0 }}>
                    <Check className="w-5 h-5" />
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.button>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
