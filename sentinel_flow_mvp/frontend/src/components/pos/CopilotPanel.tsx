"use client";

import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, ShieldCheck, X, Sparkles, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { usePOSStore } from '@/store/posStore';

// --- CUSTOM AVATARS (Replacing cheap icons) ---

const SentinelCore = ({ className }: { className?: string }) => (
  <div className={cn("relative flex items-center justify-center overflow-hidden rounded-full bg-white shadow-sm border border-slate-100", className)}>
    {/* Sweeping Scanner Beam */}
    <motion.div
      animate={{ rotate: 360 }}
      transition={{ duration: 3, repeat: Infinity, ease: "linear" }}
      className="absolute inset-[-50%] bg-[conic-gradient(from_0deg,transparent_0_300deg,rgba(6,182,212,0.8)_360deg)]"
    />
    {/* Inner Frosted Core */}
    <div className="absolute inset-[2px] bg-white/90 backdrop-blur-sm rounded-full flex items-center justify-center">
      {/* Breathing Neural Glow */}
      <motion.div 
        animate={{ scale: [1, 1.2, 1], opacity: [0.5, 1, 0.5] }}
        transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
        className="w-1/2 h-1/2 bg-cyan-400 blur-[3px] rounded-full" 
      />
    </div>
  </div>
);

const BiometricNode = ({ className }: { className?: string }) => (
  <div className={cn("relative flex items-center justify-center rounded-full bg-gradient-to-b from-slate-50 to-slate-200 border border-white shadow-[inset_0_-2px_4px_rgba(0,0,0,0.05),0_2px_4px_rgba(0,0,0,0.02)]", className)}>
    <div className="w-1/2 h-1/2 rounded-full bg-gradient-to-br from-slate-200 to-slate-300 shadow-[inset_0_1px_2px_rgba(255,255,255,0.8)]" />
  </div>
);

// --- MAIN COMPONENT ---

export default function CopilotPanel() {
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  
  const isCopilotOpen = usePOSStore((state: any) => state.isCopilotOpen);
  const toggleCopilot = usePOSStore((state: any) => state.toggleCopilot);
  const chatHistory = usePOSStore((state: any) => state.chatHistory);
  const addChatMessage = usePOSStore((state: any) => state.addChatMessage);
  const setSafetyLock = usePOSStore((state: any) => state.setSafetyLock);
  const cart = usePOSStore((state: any) => state.cart);

  useEffect(() => {
    // OPTIMIZATION: block: "nearest" prevents the browser window from jerking downward
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [chatHistory, isLoading]);

  const handleSend = async (overrideText?: any) => {
    // If called via onClick, it might receive an Event. We only want a string.
    const textToSend = typeof overrideText === 'string' ? overrideText : input.trim();
    if (!textToSend) return;
    
    if (typeof overrideText !== 'string') {
      setInput('');
    }
    
    addChatMessage({ id: Date.now().toString(), role: 'user', content: textToSend });
    setIsLoading(true);

    try {
      const cartContext = cart && cart.length > 0 
        ? `\n\n[SYSTEM NOTE: The patient is currently purchasing: ${cart.map((c: any) => c.name || c.sku_id).join(', ')}]` 
        : '';

      const response = await fetch('/api/v1/knowledge-base/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Tenant-ID': 'PHARM-001' },
        body: JSON.stringify({ query: textToSend + cartContext, top_k: 3 }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Server Error: ${response.status}`);
      }

      // Step 1: Parse the backend's structured JSON response.
      // The RAG pipeline now returns is_safe_to_dispense and
      // system_lock_reason alongside the narrative answer.
      const data = await response.json();

      // Step 2: Extract the safety fields from the backend response.
      // If the ClinicalSafetyJudge blocked this transaction,
      // is_safe_to_dispense will be false and system_lock_reason
      // will contain the reason code (e.g. CRITICAL_PREGNANCY_CONTRAINDICATION).
      const isSafe: boolean | undefined = data.is_safe_to_dispense;
      const lockReason: string | undefined = data.system_lock_reason;
      const status: string | undefined = data.status;
      const choices: string[] | undefined = data.choices;

      // Step 3: Broadcast the safety verdict to the Zustand store.
      // When is_safe_to_dispense is false, the global activeSafetyLock
      // is set, which immediately disables all checkout buttons.
      if (isSafe === false && lockReason) {
        setSafetyLock(lockReason);
      }

      // Step 4: Store the message in chat history, carrying the
      // safety fields so the rendering layer can style them.
      addChatMessage({ 
        id: (Date.now() + 1).toString(), 
        role: 'ai', 
        content: data.answer,
        sources: data.context_used,
        is_safe_to_dispense: isSafe,
        system_lock_reason: lockReason,
        status: status,
        choices: choices,
      });
    } catch (error: any) {
      addChatMessage({ 
        id: (Date.now() + 1).toString(), 
        role: 'ai', 
        content: `SYSTEM ERROR: ${error.message || "Unable to reach clinical database. Consult pharmacist."}` 
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AnimatePresence>
      {isCopilotOpen && (
        <>
          <motion.div 
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={toggleCopilot}
            className="fixed inset-0 bg-slate-900/10 backdrop-blur-sm z-40"
          />

          <div className="fixed inset-y-0 right-0 w-full max-w-[440px] z-50 p-4 md:p-6 font-sans antialiased" style={{ perspective: '1200px' }}>
            
            <motion.div
              initial={{ x: "100%", rotateY: -25, opacity: 0, scale: 0.95 }}
              animate={{ x: 0, rotateY: 0, opacity: 1, scale: 1 }}
              exit={{ x: "100%", rotateY: -15, opacity: 0, scale: 0.95 }}
              transition={{ type: "spring", damping: 35, stiffness: 300, mass: 0.8 }}
              className="h-full w-full rounded-[2.5rem] p-[1px] bg-gradient-to-br from-blue-200/60 via-rose-200/60 to-amber-200/60 shadow-[0_24px_64px_rgba(0,0,0,0.1)] origin-right"
            >
              <div className="relative h-full w-full bg-white/80 backdrop-blur-3xl rounded-[calc(2.5rem-1px)] flex flex-col overflow-hidden">
                
                <div className="absolute inset-0 opacity-[0.04] pointer-events-none mix-blend-overlay" 
                     style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg viewBox=%220 0 200 200%22 xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cfilter id=%22noiseFilter%22%3E%3CfeTurbulence type=%22fractalNoise%22 baseFrequency=%220.8%22 numOctaves=%223%22 stitchTiles=%22stitch%22/%3E%3C/filter%3E%3Crect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23noiseFilter)%22/%3E%3C/svg%3E")' }}>
                </div>

                {/* Header */}
                <div className="relative z-10 p-6 border-b border-slate-100/50 flex items-center justify-between bg-white/40">
                  <div className="flex items-center gap-3">
                    <SentinelCore className="w-10 h-10" />
                    <div>
                      <h2 className="font-bold text-slate-800 tracking-tight text-lg">Clinical Copilot</h2>
                      <p className="text-[11px] text-emerald-600 font-semibold flex items-center gap-1 uppercase tracking-wider">
                        <ShieldCheck size={12} /> Safety Guard Active
                      </p>
                    </div>
                  </div>
                  <button onClick={toggleCopilot} className="p-2 text-slate-400 hover:text-slate-700 hover:bg-slate-100/50 rounded-full transition-colors">
                    <X size={20} />
                  </button>
                </div>

                {/* Chat Area */}
                <div className="relative z-10 flex-1 overflow-y-auto p-6 space-y-6 scroll-smooth">
                  {chatHistory?.length === 0 && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="h-full flex flex-col items-center justify-center text-center space-y-4">
                      <div className="w-16 h-16 bg-gradient-to-br from-cyan-50 to-violet-50 rounded-2xl flex items-center justify-center border border-white shadow-sm">
                        <Sparkles className="w-8 h-8 text-cyan-500" />
                      </div>
                      <div>
                        <h3 className="text-slate-700 font-semibold">How can I assist?</h3>
                        <p className="text-slate-400 text-sm max-w-[200px] mt-1">Ask about interactions, dosages, or pregnancy safety.</p>
                      </div>
                    </motion.div>
                  )}

                  {chatHistory?.map((msg: any) => (
                    <motion.div 
                      initial={{ opacity: 0, y: 10, scale: 0.95 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      key={msg.id} 
                      className={cn("flex gap-3 max-w-[88%]", msg.role === 'user' ? "ml-auto flex-row-reverse" : "mr-auto")}
                    >
                      {msg.role === 'user' ? <BiometricNode className="w-8 h-8 shrink-0" /> : <SentinelCore className="w-8 h-8 shrink-0" />}
                      
                      {/* Phase 6: Polymorphic message bubble.
                          If the backend Judge blocked this transaction, the bubble
                          turns red and shows the lock reason prominently. */}
                      <div className={cn(
                        "p-4 text-[15px] leading-relaxed shadow-sm",
                        msg.role === 'user' 
                          ? "bg-white border border-slate-100 text-slate-800 rounded-2xl rounded-tr-sm"
                          : msg.is_safe_to_dispense === false
                            ? "bg-red-50 border border-red-500 text-red-900 rounded-2xl rounded-tl-sm"
                            : "bg-gradient-to-br from-slate-50 to-blue-50/30 border border-blue-100/50 text-slate-800 rounded-2xl rounded-tl-sm"
                      )}>
                        {/* Phase 6: If the Judge blocked, show the lock reason
                            as a bold red badge above the narrative text. */}
                        {msg.is_safe_to_dispense === false && msg.system_lock_reason && (
                          <div className="mb-3">
                            <span className="inline-block px-3 py-1 bg-red-600 text-white text-[11px] font-bold rounded-lg uppercase tracking-wider">
                              {msg.system_lock_reason}
                            </span>
                          </div>
                        )}
                        <p>{msg.content}</p>
                        
                        {msg.sources && msg.sources.length > 0 && (
                          <div className="mt-4 pt-3 border-t border-slate-200/50">
                            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1">
                              <ShieldCheck size={12} className="text-emerald-500" /> Verified Sources
                            </p>
                            {msg.sources.map((src: any, idx: number) => (
                              <div key={idx} className="text-xs text-slate-500 bg-white/60 p-2 rounded-lg mb-1.5 border border-slate-100 shadow-sm">
                                <span className="font-semibold text-slate-700">{src.sku_id}:</span> {src.content.substring(0, 60)}...
                              </div>
                            ))}
                          </div>
                        )}
                        
                        {/* Phase 2: Disambiguation choices */}
                        {msg.status === "disambiguate" && msg.choices && msg.choices.length > 0 && (
                          <div className="mt-4 flex flex-wrap gap-2">
                            {msg.choices.map((choice: string, idx: number) => (
                              <motion.button
                                key={idx}
                                whileHover={{ scale: 1.05 }}
                                whileTap={{ scale: 0.95 }}
                                onClick={() => handleSend(choice)}
                                className="px-3 py-1.5 bg-white border border-cyan-200 text-cyan-700 hover:bg-cyan-50 text-sm rounded-xl transition-colors shadow-sm"
                              >
                                {choice}
                              </motion.button>
                            ))}
                          </div>
                        )}
                      </div>
                    </motion.div>
                  ))}
                  
                  {/* THE QUANTUM SYNAPSE LOADER */}
                  {isLoading && (
                    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3 max-w-[85%] mr-auto items-center">
                      <SentinelCore className="w-8 h-8 shrink-0" />
                      <div className="relative overflow-hidden px-5 py-3 rounded-2xl rounded-tl-sm bg-white/60 border border-white/80 shadow-sm min-w-[120px] flex items-center justify-center">
                        <motion.div 
                          animate={{ x: ["-200%", "200%"] }}
                          transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
                          className="absolute inset-0 w-full bg-gradient-to-r from-transparent via-cyan-400/20 to-transparent skew-x-12"
                        />
                        <motion.span 
                          animate={{ opacity: [0.4, 1, 0.4] }}
                          transition={{ duration: 2, repeat: Infinity, ease: "easeInOut" }}
                          className="text-[10px] font-bold tracking-[0.2em] uppercase bg-gradient-to-r from-cyan-600 to-blue-600 bg-clip-text text-transparent"
                        >
                          Synthesizing
                        </motion.span>
                      </div>
                    </motion.div>
                  )}
                  <div ref={messagesEndRef} />
                </div>

                {/* Input Area */}
                <div className="relative z-10 p-4 bg-white/60 backdrop-blur-md border-t border-slate-100/50">
                  <div className="relative flex items-center group">
                    <input
                      type="text"
                      value={input}
                      onChange={(e) => setInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                      placeholder="Verify clinical safety..."
                      className="w-full bg-white border border-slate-200 focus:border-cyan-400 focus:ring-4 focus:ring-cyan-100 rounded-2xl py-4 pl-5 pr-14 text-[15px] text-slate-800 transition-all outline-none shadow-sm placeholder-slate-400"
                      disabled={isLoading}
                    />
                    <motion.button 
                      whileHover={{ scale: 1.1 }}
                      whileTap={{ scale: 0.9 }}
                      onClick={() => handleSend()}
                      disabled={isLoading || !input.trim()}
                      className="absolute right-2 p-2.5 bg-slate-900 hover:bg-slate-800 disabled:bg-slate-300 text-white rounded-xl transition-colors shadow-md flex items-center justify-center"
                    >
                      {isLoading ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} className="ml-0.5" />}
                    </motion.button>
                  </div>
                </div>

              </div>
            </motion.div>
          </div>
        </>
      )}
    </AnimatePresence>
  );
}
