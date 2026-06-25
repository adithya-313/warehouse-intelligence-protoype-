import React from 'react';
import Link from 'next/link';
import { ArrowLeft } from 'lucide-react';
import Scorecard from '@/components/suppliers/Scorecard';

export default function SuppliersPage() {
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 p-8">
      <div className="max-w-6xl mx-auto">
        <header className="flex justify-between items-center mb-10">
          <div className="flex items-center gap-4">
            <Link href="/pos" className="p-2 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-full hover:bg-gray-50 transition-colors">
              <ArrowLeft size={20} className="text-gray-600 dark:text-gray-300" />
            </Link>
            <h1 className="text-3xl font-black tracking-tight text-gray-900 dark:text-white">Vendor Intelligence</h1>
          </div>
        </header>
        
        <Scorecard supplierId="SUPP-001" />
      </div>
    </div>
  );
}
