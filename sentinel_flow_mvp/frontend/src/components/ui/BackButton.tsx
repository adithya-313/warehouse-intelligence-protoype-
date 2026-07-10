"use client";

import React from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { ArrowLeft } from 'lucide-react';

interface BackButtonProps {
  href: string;
  label?: string;
}

export default function BackButton({ href, label = 'Back' }: BackButtonProps) {
  return (
    <Link href={href}>
      <motion.span
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.98 }}
        className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-slate-600 hover:text-slate-900 bg-white/5 hover:bg-white/10 border border-white/10 rounded-full transition-all duration-200 backdrop-blur-md cursor-pointer"
      >
        <ArrowLeft className="w-4 h-4" />
        {label}
      </motion.span>
    </Link>
  );
}
