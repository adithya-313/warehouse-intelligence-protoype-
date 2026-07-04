"use client";

import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';

export default function GlobalCursor() {
  const [mousePosition, setMousePosition] = useState({ x: 0, y: 0 });
  const [isHovering, setIsHovering] = useState(false);

  useEffect(() => {
    const updateMousePosition = (e: MouseEvent) => {
      setMousePosition({ x: e.clientX, y: e.clientY });
      
      // Check if hovering over a clickable element
      const target = e.target as HTMLElement;
      const isClickable = window.getComputedStyle(target).cursor === 'pointer' || target.tagName.toLowerCase() === 'button' || target.tagName.toLowerCase() === 'a';
      setIsHovering(isClickable);
    };

    window.addEventListener('mousemove', updateMousePosition);
    return () => window.removeEventListener('mousemove', updateMousePosition);
  }, []);

  // Hide on touch devices
  if (typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches) {
    return null;
  }

  return (
    <motion.div
      className="fixed top-0 left-0 w-6 h-6 bg-blue-500/20 border border-blue-400/50 backdrop-blur-sm rounded-full pointer-events-none z-[9999] flex items-center justify-center mix-blend-multiply"
      animate={{
        x: mousePosition.x - 12,
        y: mousePosition.y - 12,
        scale: isHovering ? 2.5 : 1,
        backgroundColor: isHovering ? "rgba(16, 185, 129, 0.1)" : "rgba(56, 189, 248, 0.2)",
        borderColor: isHovering ? "rgba(16, 185, 129, 0.4)" : "rgba(56, 189, 248, 0.5)"
      }}
      transition={{ type: "spring", stiffness: 800, damping: 35, mass: 0.1 }}
    >
      <motion.div 
        className="w-1 h-1 bg-blue-600 rounded-full"
        animate={{ scale: isHovering ? 0 : 1 }}
      />
    </motion.div>
  );
}
