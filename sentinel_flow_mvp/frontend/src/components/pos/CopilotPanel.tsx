"use client";

import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, ShieldCheck, Bot, User, X, Sparkles, Loader2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { usePOSStore } from '@/store/posStore';

export default function CopilotPanel() {
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  
  const isCopilotOpen = usePOSStore((state: any) => state.isCopilotOpen);
  const toggleCopilot = usePOSStore((state: any) => state.toggleCopilot);
  const chatHistory = usePOSStore((state: any) => state.chatHistory);
  const addChatMessage = usePOSStore((state: any) => state.addChatMessage);
  const cart = usePOSStore((state: any) => state.cart);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, isLoading]);

  const handleSend = async () => {
    if (!input.trim()) return;
    const userText = input.trim();
    setInput('');
    
    addChatMessage({ id: Date.now().toString(), role: 'user', content: userText });
    setIsLoading(true);

    try {
      const cartContext = cart && cart.length > 0 
        ? `\n\n[SYSTEM NOTE: The patient is currently purchasing: ${cart.map((c: any) => c.name || c.sku_id).join(', ')}]` 
        : '';

      const response = await fetch('/api/v1/knowledge-base/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: userText + cartContext, top_k: 3 }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Server Error: ${response.status}`);
      }

      const data = await response.json();

      addChatMessage({ 
        id: (Date.now() + 1).toString(), 
        role: 'ai', 
        content: data.answer,
        sources: data.context_used 
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
          {/* Backdrop Blur Overlay */}
          <motion.div 
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            onClick={toggleCopilot}
            className="fixed inset-0 bg-slate-900/10 backdrop-blur-sm z-40"
          />

          {/* 3D Perspective Wrapper - Enforcing font-sans and antialiased for Apple typography */}
          <div className="fixed inset-y-0 right-0 w-full max-w-[440px] z-50 p-4 md:p-6 font-sans antialiased" style={{ perspective: '1200px' }}>
            
            {/* DESIGN TOKEN: Iridescent Pearl Wrapper */}
            <motion.div
              initial={{ x: "100%", rotateY: -25, opacity: 0, scale: 0.95 }}
              animate={{ x: 0, rotateY: 0, opacity: 1, scale: 1 }}
              exit={{ x: "100%", rotateY: -15, opacity: 0, scale: 0.95 }}
              transition={{ type: "spring", damping: 35, stiffness: 300, mass: 0.8 }}
              className="h-full w-full rounded-[2.5rem] p-[1px] bg-gradient-to-br from-blue-200/60 via-rose-200/60 to-amber-200/60 shadow-[0_24px_64px_rgba(0,0,0,0.1)] origin-right"
            >
              {/* Quantum Glass Inner Container */}
              <div className="relative h-full w-full bg-white/80 backdrop-blur-3xl rounded-[calc(2.5rem-1px)] flex flex-col overflow-hidden">
                
                {/* Dynamic SVG Film Grain Texture */}
                <div className="absolute inset-0 opacity-[0.04] pointer-events-none mix-blend-overlay" 
                     style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg viewBox=%220 0 200 200%22 xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cfilter id=%22noiseFilter%22%3E%3CfeTurbulence type=%22fractalNoise%22 baseFrequency=%220.8%22 numOctaves=%223%22 stitchTiles=%22stitch%22/%3E%3C/filter%3E%3Crect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23noiseFilter)%22/%3E%3C/svg%3E")' }}>
                </div>

                {/* Header */}
                <div className="relative z-10 p-6 border-b border-slate-100/50 flex items-center justify-between bg-white/40">
                  <div className="flex items-center gap-3">
                    <div className="relative flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-50 to-violet-50 border border-cyan-100/50 shadow-sm">
                      <Bot className="w-5 h-5 text-cyan-600" />
                      <span className="absolute top-0 right-0 w-2.5 h-2.5 bg-emerald-400 border-2 border-white rounded-full"></span>
                    </div>
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
                      <div className="w-16 h-16 bg-gradient-to-br from-cyan-100/50 to-violet-100/50 rounded-2xl flex items-center justify-center border border-white shadow-sm">
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
                      <div className={cn(
                        "w-8 h-8 rounded-full flex items-center justify-center shrink-0 shadow-sm border border-white/50",
                        msg.role === 'user' ? "bg-slate-100 text-slate-600" : "bg-gradient-to-br from-cyan-500 to-violet-500 text-white"
                      )}>
                        {msg.role === 'user' ? <User size={14} /> : <Bot size={14} />}
                      </div>
                      
                      <div className={cn(
                        "p-4 text-sm leading-relaxed shadow-sm",
                        msg.role === 'user' 
                          ? "bg-white border border-slate-100 text-slate-800 rounded-2xl rounded-tr-sm" 
                          : "bg-gradient-to-br from-slate-50 to-blue-50/30 border border-blue-100/50 text-slate-800 rounded-2xl rounded-tl-sm"
                      )}>
                        <p>{msg.content}</p>
                        
                        {/* Verified Sources */}
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
                      </div>
                    </motion.div>
                  ))}
                  
                  {/* THE QUANTUM SYNAPSE LOADER */}
                  {isLoading && (
                    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3 max-w-[85%] mr-auto items-center">
                      <div className="w-8 h-8 rounded-full bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center shrink-0 shadow-sm border border-white/80">
                        <Bot size={14} className="text-slate-400" />
                      </div>
                      <div className="relative overflow-hidden px-5 py-3 rounded-2xl rounded-tl-sm bg-white/60 border border-white/80 shadow-sm min-w-[120px] flex items-center justify-center">
                        {/* Liquid Light Beam */}
                        <motion.div 
                          animate={{ x: ["-200%", "200%"] }}
                          transition={{ duration: 1.5, repeat: Infinity, ease: "easeInOut" }}
                          className="absolute inset-0 w-full bg-gradient-to-r from-transparent via-cyan-400/20 to-transparent skew-x-12"
                        />
                        {/* Breathing Text */}
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
                      className="w-full bg-white border border-slate-200 focus:border-cyan-400 focus:ring-4 focus:ring-cyan-100 rounded-2xl py-4 pl-5 pr-14 text-sm text-slate-800 transition-all outline-none shadow-sm placeholder-slate-400"
                      disabled={isLoading}
                    />
                    {/* Magnetic Send Button */}
                    <motion.button 
                      whileHover={{ scale: 1.1 }}
                      whileTap={{ scale: 0.9 }}
                      onClick={handleSend}
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
