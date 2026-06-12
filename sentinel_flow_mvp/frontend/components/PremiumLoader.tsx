'use client';

import { motion } from 'framer-motion';

export default function PremiumLoader({ label }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-12">
      <div className="relative flex items-center gap-1.5">
        {[0, 1, 2, 3, 4].map((i) => (
          <motion.div
            key={i}
            className="h-3 w-1 rounded-full bg-accent-indigo/70"
            animate={{
              height: ['12px', '28px', '12px'],
              opacity: [0.3, 0.9, 0.3],
            }}
            transition={{
              duration: 1.2,
              repeat: Infinity,
              delay: i * 0.12,
              ease: 'easeInOut',
            }}
          />
        ))}
      </div>
      {label && (
        <motion.p
          className="text-sm text-white/40 font-mono tracking-wide"
          animate={{ opacity: [0.4, 0.8, 0.4] }}
          transition={{ duration: 2, repeat: Infinity }}
        >
          {label}
        </motion.p>
      )}
    </div>
  );
}
