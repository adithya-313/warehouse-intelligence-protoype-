"use client";

import React, { useEffect, useState } from 'react';
import { motion, useMotionValue, useSpring } from 'framer-motion';

export default function GlobalCursor() {
  const [isHovering, setIsHovering] = useState(false);
  
  // OPTIMIZATION: useMotionValue bypasses React state, preventing 60FPS re-renders.
  const mouseX = useMotionValue(-100);
  const mouseY = useMotionValue(-100);
  
  // Ultra-tight spring physics for zero-latency tracking
  const springX = useSpring(mouseX, { damping: 40, stiffness: 800, mass: 0.05 });
  const springY = useSpring(mouseY, { damping: 40, stiffness: 800, mass: 0.05 });

  useEffect(() => {
    const updateMousePosition = (e: MouseEvent) => {
      mouseX.set(e.clientX);
      mouseY.set(e.clientY);
      
      const target = e.target as HTMLElement;
      const isClickable = window.getComputedStyle(target).cursor === 'pointer' || 
                          target.tagName.toLowerCase() === 'button' || 
                          target.tagName.toLowerCase() === 'a' ||
                          target.closest('button') !== null ||
                          target.closest('a') !== null;
      setIsHovering(isClickable);
    };

    window.addEventListener('mousemove', updateMousePosition, { passive: true });
    return () => window.removeEventListener('mousemove', updateMousePosition);
  }, [mouseX, mouseY]);

  if (typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches) {
    return null;
  }

  return (
    <motion.div
      className="fixed top-0 left-0 pointer-events-none z-[9999] flex items-center justify-center rounded-full"
      style={{
        x: springX,
        y: springY,
        translateX: "-50%",
        translateY: "-50%"
      }}
      animate={{
        width: isHovering ? 48 : 16,
        height: isHovering ? 48 : 16,
        backgroundColor: isHovering ? "rgba(255, 255, 255, 0.1)" : "rgba(255, 255, 255, 0)",
        backdropFilter: isHovering ? "blur(4px)" : "blur(0px)",
        border: isHovering ? "1px solid rgba(255, 255, 255, 0.4)" : "1.5px solid rgba(148, 163, 184, 0.8)",
        boxShadow: isHovering ? "0 4px 12px rgba(0,0,0,0.05), inset 0 0 8px rgba(255,255,255,0.2)" : "none"
      }}
      transition={{ type: "spring", stiffness: 500, damping: 28, mass: 0.1 }}
    />
  );
}
