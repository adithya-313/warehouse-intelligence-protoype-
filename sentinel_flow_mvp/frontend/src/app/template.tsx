"use client";

import { motion } from 'framer-motion';

export default function Template({ children }: { children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ 
        duration: 0.15, 
        ease: [0.22, 1, 0.36, 1] // Apple-style custom easing curve
      }}
      className="w-full min-h-screen will-change-[opacity]"
    >
      {children}
    </motion.div>
  );
}
