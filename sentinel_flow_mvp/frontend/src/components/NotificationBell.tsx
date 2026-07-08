"use client";

import React, { useState, useEffect } from 'react';
import { api, NotificationResponse } from '../services/api';

export function NotificationBell() {
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

  // Hydration Guard: Render a safe placeholder on SSR
  if (!mounted) {
    return (
      <button className="p-2 relative rounded-full hover:bg-gray-100 text-gray-600">
        🔔
      </button>
    );
  }

  return (
    <div className="relative">
      {/* Bell Button */}
      <button 
        onClick={() => setIsOpen(!isOpen)} 
        className="p-2 relative rounded-full hover:bg-gray-100 text-gray-600 transition-colors focus:outline-none"
      >
        <span className="text-xl">🔔</span>
        {unreadCount > 0 && (
          <span className="absolute top-1 right-1 bg-red-500 text-white text-[10px] font-bold rounded-full h-4 w-4 flex items-center justify-center animate-pulse">
            {unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown — uses z-50 from the design token system (parent stack is z-10) */}
      {isOpen && (
        <div 
          className="absolute right-0 mt-2 w-80 bg-white rounded-lg shadow-2xl border border-gray-100 flex flex-col pointer-events-auto z-50"
        >
          <div className="p-4 border-b border-gray-100 bg-gray-50 rounded-t-lg">
            <h3 className="text-sm font-semibold text-gray-900">Notification Center</h3>
          </div>

          <div className="max-h-64 overflow-y-auto">
            {loading ? (
              <div className="p-4 text-center text-xs text-gray-500">Loading alerts...</div>
            ) : notifications.length === 0 ? (
              <div className="p-4 text-center text-xs text-gray-500 font-medium">
                No recent alerts.
              </div>
            ) : (
              notifications.map((notification) => {
                if (!notification) return null;
                return (
                  <div 
                    key={notification.id || Math.random()} 
                    className="p-4 border-b border-gray-50 hover:bg-gray-50 transition-colors flex flex-col"
                  >
                    <span className="text-xs font-semibold text-red-600 uppercase tracking-wider mb-1">
                      {notification.alert_type || "ALERT"}
                    </span>
                    <span className="text-sm font-bold text-gray-900 mb-1">
                      {notification.title || "Preemptive Order Alert"}
                    </span>
                    <p className="text-xs text-gray-600 leading-relaxed">
                      {notification.message || "Action recommended."}
                    </p>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
