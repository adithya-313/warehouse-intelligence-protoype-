"use client";

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { api, NotificationResponse } from '../services/api';
import { Bell } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { getDiseaseStyle } from '@/utils/diseaseIdentity';

export function NotificationBell() {
  const router = useRouter();
  const [notifications, setNotifications] = useState<NotificationResponse[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setMounted(true);
    // Fetch notifications safely on client mount
    setLoading(true);
    api.fetchNotifications()
      .then((data) => {
        if (Array.isArray(data)) {
          setNotifications(data);
        } else {
          setNotifications([]);
        }
      })
      .catch((err) => {
        console.error("Failed to fetch notifications:", err);
        setNotifications([]);
      })
      .finally(() => setLoading(false));
  }, []);

  const unreadCount = notifications.filter(n => n && !n.is_read).length;

  const handleNotificationClick = (notification: NotificationResponse) => {
    // Optimistic read update — reflect immediately, don't wait for the PATCH.
    if (notification.id && !notification.is_read) {
      setNotifications((prev) =>
        prev.map((n) => (n.id === notification.id ? { ...n, is_read: true } : n))
      );
      api.markNotificationRead(notification.id).catch(console.error);
    }
    setIsOpen(false);
    
    if (notification.alert_type === 'OVERDUE_ORDER') {
      // Deep link to procurement page (optionally with po_id if we have one)
      const po_id = notification.reference_id;
      router.push(po_id ? `/orders?po_id=${encodeURIComponent(po_id)}` : '/orders');
      return;
    }

    // Deep-link to the Radar page, identifying the target disease via the
    // query param (the Radar page pre-selects + scrolls to the matching card).
    const disease = notification.disease_category;
    router.push(disease ? `/health-risk-radar?disease=${encodeURIComponent(disease)}` : '/health-risk-radar');
  };

  // Hydration Guard: Render a safe placeholder on SSR
  if (!mounted) {
    return (
      <button className="p-2 relative rounded-full hover:bg-gray-100 text-gray-600">
        <Bell className="w-5 h-5 text-slate-700" />
      </button>
    );
  }

  return (
    <div className="relative">
      {/* Bell Button */}
      <motion.button 
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        onClick={() => setIsOpen(!isOpen)} 
        data-testid="notification-bell"
        className="p-2 relative rounded-full hover:bg-gray-100 text-gray-600 transition-colors focus:outline-none"
      >
        <Bell className="w-5 h-5 text-slate-700" />
        {unreadCount > 0 && (
          <span data-testid="notification-unread-dot" className="absolute top-0 right-0 w-2.5 h-2.5 bg-red-500 rounded-full border-2 border-white">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
          </span>
        )}
      </motion.button>

      {/* Dropdown — uses z-50 from the design token system (parent stack is z-10) */}
      <AnimatePresence>
        {isOpen && (
          <motion.div 
            initial={{ opacity: 0, y: -10, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -10, scale: 0.95 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="absolute right-0 mt-2 w-80 bg-white/80 backdrop-blur-xl border border-white/60 shadow-[0_8px_32px_rgba(0,0,0,0.08)] rounded-2xl z-50 overflow-hidden"
          >
            <div className="p-4 border-b border-slate-100/50 bg-white/40 rounded-t-lg">
              <h3 className="text-sm font-semibold text-gray-900">Notification Center</h3>
            </div>

            <div className="max-h-64 overflow-y-auto">
              {loading ? (
                <div className="p-4 text-center text-xs text-gray-500">Loading alerts...</div>
              ) : notifications.length === 0 ? (
                <div className="flex flex-col items-center justify-center p-8 text-center">
                  <Bell className="w-8 h-8 text-slate-300 mb-2 opacity-50" />
                  <div className="text-sm font-medium text-slate-500">No new notifications</div>
                </div>
              ) : (
                notifications.map((notification) => {
                  if (!notification) return null;
                  const style = getDiseaseStyle(notification.disease_category);
                  const Icon = style.icon;
                  return (
                    <button
                      key={notification.id ?? Math.random()}
                      data-testid="notification-item"
                      onClick={() => handleNotificationClick(notification)}
                      className="w-full text-left hover:bg-white/50 transition-colors p-4 border-b border-slate-100/50 last:border-0 flex items-start gap-3"
                    >
                      <span className={`mt-0.5 p-2 rounded-full ${style.badgeClass}`}>
                        <Icon className="w-4 h-4" style={{ color: style.color }} />
                      </span>
                      <span className="flex flex-col flex-1 min-w-0">
                        <span className={`text-sm font-bold ${notification.is_read ? 'text-gray-500' : 'text-gray-900'}`}>
                          {notification.title || "Preemptive Order Alert"}
                        </span>
                        <p className="text-xs text-gray-600 leading-relaxed">
                          {notification.message || "Action recommended."}
                        </p>
                        {notification.alert_type && (
                          <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider mt-1">
                            {notification.alert_type}
                          </span>
                        )}
                      </span>
                    </button>
                  );
                })
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}