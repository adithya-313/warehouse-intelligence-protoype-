"use client";

import React from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { ArrowLeft } from 'lucide-react';

interface BackButtonProps {
  href: string;
}

export default function BackButton({ href }: BackButtonProps) {
  return (
    <Link href={href}>
      <motion.div
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        className="p-3 bg-white/60 backdrop-blur-md border border-white/80 shadow-sm rounded-2xl text-slate-500 hover:text-slate-800 hover:bg-white transition-colors flex items-center justify-center group will-change-transform cursor-pointer"
      >
        <ArrowLeft size={24} className="group-hover:-translate-x-1 transition-transform" />
      </motion.div>
    </Link>
  );
}
