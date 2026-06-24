"use client";

import React, { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, ShieldCheck, Loader2, Bot, User, AlertTriangle } from 'lucide-react';
import { cn } from '@/lib/utils';
// Adjust import based on your actual store export name
import { usePOSStore } from '@/store/posStore'; 

export default function CopilotPanel() {
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  
  // Assuming these exist in your updated store
  const isCopilotOpen = usePOSStore((state: any) => state.isCopilotOpen);
  const chatHistory = usePOSStore((state: any) => state.chatHistory);
  const addChatMessage = usePOSStore((state: any) => state.addChatMessage);
  const cart = usePOSStore((state: any) => state.cart); // Cross-reference cart

  // Auto-scroll to bottom of chat
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, isLoading]);

  const handleSend = async () => {
    if (!input.trim()) return;

    const userText = input.trim();
    setInput('');
    
    // 1. Add User Message to UI instantly (Optimistic UI)
    addChatMessage({ id: Date.now().toString(), role: 'user', content: userText });
    setIsLoading(true);

    try {
      // 2. Cross-Reference: Append current cart items to the query context behind the scenes
      const cartContext = cart && cart.length > 0 
        ? `\n\n[SYSTEM NOTE: The patient is currently purchasing: ${cart.map((c: any) => c.name || c.sku_id).join(', ')}]` 
        : '';

      // 3. Call Backend API
      const response = await fetch('/api/v1/knowledge-base/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          query: userText + cartContext,
          top_k: 3 
        }),
      });

      const data = await response.json();

      // 4. Add AI Response to UI
      addChatMessage({ 
        id: (Date.now() + 1).toString(), 
        role: 'ai', 
        content: data.answer,
        sources: data.context_used 
      });

    } catch (error) {
      addChatMessage({ 
        id: (Date.now() + 1).toString(), 
        role: 'ai', 
        content: "SYSTEM ERROR: Unable to reach clinical database. Consult pharmacist." 
      });
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <AnimatePresence>
      {isCopilotOpen && (
        <motion.div
          initial={{ x: 400, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 400, opacity: 0 }}
          transition={{ type: "spring", stiffness: 300, damping: 30 }}
          className="fixed right-0 top-0 h-screen w-96 bg-white/90 dark:bg-gray-900/90 backdrop-blur-xl border-l border-gray-200 dark:border-gray-800 shadow-2xl flex flex-col z-50"
        >
          {/* Header */}
          <div className="p-4 border-b border-gray-200 dark:border-gray-800 flex items-center gap-3 bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-900/20 dark:to-indigo-900/20">
            <div className="p-2 bg-blue-500 rounded-lg shadow-inner">
              <ShieldCheck className="w-5 h-5 text-white" />
            </div>
            <div>
              <h2 className="font-bold text-gray-900 dark:text-white text-sm">Clinical Copilot</h2>
              <p className="text-xs text-blue-600 dark:text-blue-400 font-medium flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>
                Safety Guard Active
              </p>
            </div>
          </div>

          {/* Chat Area */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4 scroll-smooth">
            {chatHistory?.length === 0 && (
              <div className="text-center text-gray-400 text-sm mt-10 flex flex-col items-center gap-2">
                <Bot className="w-8 h-8 opacity-50" />
                <p>Ask about interactions, dosages, or pregnancy safety.</p>
              </div>
            )}

            {chatHistory?.map((msg: any) => (
              <motion.div 
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                key={msg.id} 
                className={cn(
                  "flex gap-3 max-w-[85%]",
                  msg.role === 'user' ? "ml-auto flex-row-reverse" : "mr-auto"
                )}
              >
                <div className={cn(
                  "w-8 h-8 rounded-full flex items-center justify-center shrink-0 shadow-sm",
                  msg.role === 'user' ? "bg-indigo-100 text-indigo-600" : "bg-blue-600 text-white"
                )}>
                  {msg.role === 'user' ? <User size={16} /> : <Bot size={16} />}
                </div>
                
                <div className={cn(
                  "p-3 rounded-2xl text-sm shadow-sm",
                  msg.role === 'user' 
                    ? "bg-indigo-600 text-white rounded-tr-none" 
                    : "bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-200 border border-gray-100 dark:border-gray-700 rounded-tl-none"
                )}>
                  <p className="leading-relaxed">{msg.content}</p>
                  
                  {/* Source Citations (Trust Building) */}
                  {msg.sources && msg.sources.length > 0 && (
                    <div className="mt-3 pt-2 border-t border-gray-100 dark:border-gray-700">
                      <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-1">Verified Sources</p>
                      {msg.sources.map((src: any, idx: number) => (
                        <div key={idx} className="text-xs text-gray-500 bg-gray-50 dark:bg-gray-900 p-1.5 rounded mb-1 border border-gray-100 dark:border-gray-800">
                          {src.sku_id}: {src.content.substring(0, 60)}...
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </motion.div>
            ))}
            
            {/* Loading Skeleton */}
            {isLoading && (
              <div className="flex gap-3 max-w-[85%] mr-auto">
                <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center shrink-0 shadow-sm">
                  <Loader2 className="w-4 h-4 text-white animate-spin" />
                </div>
                <div className="p-4 rounded-2xl bg-white dark:bg-gray-800 border border-gray-100 dark:border-gray-700 rounded-tl-none flex items-center gap-1">
                  <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></span>
                  <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></span>
                  <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Input Area */}
          <div className="p-4 bg-white dark:bg-gray-900 border-t border-gray-200 dark:border-gray-800">
            <div className="relative flex items-center">
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSend()}
                placeholder="Verify clinical safety..."
                className="w-full bg-gray-100 dark:bg-gray-800 border-transparent focus:border-blue-500 focus:ring-2 focus:ring-blue-200 dark:focus:ring-blue-900 rounded-full py-3 pl-4 pr-12 text-sm transition-all outline-none"
                disabled={isLoading}
              />
              <button 
                onClick={handleSend}
                disabled={isLoading || !input.trim()}
                className="absolute right-2 p-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 text-white rounded-full transition-colors shadow-md"
              >
                <Send size={16} className={cn(isLoading && "opacity-0")} />
                {isLoading && <Loader2 size={16} className="absolute top-2 left-2 animate-spin" />}
              </button>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
