"use client";

import React, { useEffect, useState } from 'react';
import { motion, useMotionValue, useTransform, useSpring } from 'framer-motion';
import { TrendingDown, Truck, ShieldAlert, AlertOctagon, CheckCircle2 } from 'lucide-react';
import { cn } from '@/lib/utils';

export default function Scorecard({ supplierId = "SUPP-001" }: { supplierId?: string }) {
  const [data, setData] = useState<any>(null);
  const [isLoading, setIsLoading] = useState(true);

  // 3D Spatial Parallax Hooks
  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const mouseXSpring = useSpring(x, { stiffness: 300, damping: 30 });
  const mouseYSpring = useSpring(y, { stiffness: 300, damping: 30 });
  const rotateX = useTransform(mouseYSpring, [-0.5, 0.5], ["5deg", "-5deg"]);
  const rotateY = useTransform(mouseXSpring, [-0.5, 0.5], ["-5deg", "5deg"]);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    const xPct = mouseX / width - 0.5;
    const yPct = mouseY / height - 0.5;
    x.set(xPct);
    y.set(yPct);
  };

  const handleMouseLeave = () => {
    x.set(0);
    y.set(0);
  };

  useEffect(() => {
    const fetchScorecard = async () => {
      try {
        const res = await fetch(`/api/v1/suppliers/${supplierId}/scorecard`, {
          headers: { 'X-Tenant-ID': 'PHARM-001' }
        });
        if (!res.ok) throw new Error("No data");
        const json = await res.json();
        setData(json);
      } catch (err) {
        setData({
          supplier_id: supplierId,
          name: "Apex Pharma Distributors (DEMO)",
          financial_loss_rupees: 14500,
          delivery_success_rate: 82,
          trust_score: 65,
          risk_level: "HIGH",
          recent_failures: 3
        });
      } finally {
        setIsLoading(false);
      }
    };
    fetchScorecard();
  }, [supplierId]);

  if (isLoading) return (
    <div className="w-full max-w-5xl mx-auto h-[400px] rounded-[2.5rem] bg-white/40 backdrop-blur-xl animate-pulse border border-white/80 shadow-sm"></div>
  );

  const isHighRisk = data.risk_level === "HIGH" || data.trust_score < 70;

  return (
    <div 
      className="w-full max-w-5xl mx-auto perspective-[2000px]"
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      <motion.div 
        style={{ rotateX, rotateY, transformStyle: "preserve-3d" }}
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 400, damping: 40 }}
        className="relative rounded-[2.5rem] p-[1px] bg-gradient-to-br from-blue-200/60 via-rose-200/60 to-amber-200/60 shadow-[0_32px_64px_rgba(0,0,0,0.08)] will-change-transform"
      >
        {/* Quantum Glass Inner Container */}
        <div className="relative bg-white/70 backdrop-blur-3xl rounded-[calc(2.5rem-1px)] p-10 md:p-12 overflow-hidden" style={{ transform: "translateZ(20px)" }}>
          
          {/* Dynamic SVG Film Grain */}
          <div className="absolute inset-0 opacity-[0.03] pointer-events-none mix-blend-overlay" 
               style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg viewBox=%220 0 200 200%22 xmlns=%22http://www.w3.org/2000/svg%22%3E%3Cfilter id=%22noiseFilter%22%3E%3CfeTurbulence type=%22fractalNoise%22 baseFrequency=%220.8%22 numOctaves=%223%22 stitchTiles=%22stitch%22/%3E%3C/filter%3E%3Crect width=%22100%25%22 height=%22100%25%22 filter=%22url(%23noiseFilter)%22/%3E%3C/svg%3E")' }}>
          </div>

          {/* Header Section */}
          <div className="flex justify-between items-start mb-12 relative z-10" style={{ transform: "translateZ(30px)" }}>
            <div>
              <h2 className="text-3xl font-bold text-slate-900 tracking-tight flex items-center gap-3">
                {data.name}
                {isHighRisk ? <ShieldAlert className="text-rose-500 w-8 h-8" /> : <CheckCircle2 className="text-emerald-500 w-8 h-8" />}
              </h2>
              <p className="text-slate-500 text-sm mt-2 font-medium tracking-wide uppercase">ID: {data.supplier_id} • Real-time Vendor Telemetry</p>
            </div>
            <div className={cn(
              "px-5 py-2 rounded-2xl text-sm font-bold tracking-widest uppercase shadow-sm border",
              isHighRisk ? "bg-rose-50 text-rose-600 border-rose-100" : "bg-emerald-50 text-emerald-600 border-emerald-100"
            )}>
              {data.risk_level || (isHighRisk ? "HIGH RISK" : "TRUSTED")}
            </div>
          </div>

          {/* Metrics Grid */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 relative z-10" style={{ transform: "translateZ(40px)" }}>
            
            {/* 1. Liquid Mercury Financial Loss Card */}
            <motion.div 
              whileHover={{ scale: 1.02, y: -5 }}
              className={cn(
                "relative p-8 rounded-[2rem] border shadow-sm overflow-hidden group bg-white/80",
                isHighRisk ? "border-rose-200/50" : "border-slate-100"
              )}
            >
              {/* Chromatic Aberration Glow if High Risk */}
              {isHighRisk && (
                <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 shadow-[inset_0_0_20px_rgba(225,29,72,0.1),0_0_20px_rgba(6,182,212,0.1)] pointer-events-none rounded-[2rem]" />
              )}
              <div className="flex items-center gap-3 text-rose-500 mb-4 relative z-10">
                <TrendingDown size={24} />
                <h3 className="font-semibold tracking-wide">Financial Loss</h3>
              </div>
              <p className="text-5xl font-black tracking-tighter bg-gradient-to-br from-rose-600 via-red-500 to-orange-500 bg-clip-text text-transparent relative z-10">
                ₹{data.financial_loss_rupees.toLocaleString()}
              </p>
              <p className="text-xs text-rose-500/80 mt-3 font-semibold uppercase tracking-wider relative z-10">Capital dropped due to shortfalls</p>
            </motion.div>

            {/* 2. Kinetic SLA Ring Card */}
            <motion.div 
              whileHover={{ scale: 1.02, y: -5 }}
              className="relative p-8 rounded-[2rem] border border-slate-100 shadow-sm bg-white/80 flex flex-col items-center justify-center"
            >
              <div className="absolute top-8 left-8 flex items-center gap-3 text-blue-500">
                <Truck size={20} />
                <h3 className="font-semibold tracking-wide">Delivery SLA</h3>
              </div>
              
              {/* SVG Kinetic Ring */}
              <div className="relative w-32 h-32 mt-6">
                <svg className="w-full h-full transform -rotate-90" viewBox="0 0 100 100">
                  <circle cx="50" cy="50" r="40" stroke="currentColor" strokeWidth="8" fill="transparent" className="text-slate-100" />
                  <motion.circle 
                    initial={{ pathLength: 0 }}
                    animate={{ pathLength: data.delivery_success_rate / 100 }}
                    transition={{ duration: 2, ease: "easeOut", delay: 0.2 }}
                    cx="50" cy="50" r="40" stroke="currentColor" strokeWidth="8" fill="transparent" strokeLinecap="round"
                    className={data.delivery_success_rate > 90 ? "text-emerald-500" : "text-amber-500"}
                  />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center flex-col">
                  <span className="text-3xl font-black text-slate-800 tracking-tighter">{data.delivery_success_rate}%</span>
                </div>
              </div>
            </motion.div>

            {/* 3. Elastic Trust Matrix Card */}
            <motion.div 
              whileHover={{ scale: 1.02, y: -5 }}
              className="relative p-8 rounded-[2rem] border border-slate-100 shadow-sm bg-white/80 overflow-hidden"
            >
              {/* Elastic Morphing Background Blob */}
              <motion.div 
                animate={{ 
                  borderRadius: isHighRisk ? ["20%", "40%", "20%"] : ["40%", "50%", "40%"],
                  rotate: isHighRisk ? [0, 90, 0] : [0, 45, 0]
                }}
                transition={{ duration: isHighRisk ? 4 : 8, repeat: Infinity, ease: "easeInOut" }}
                className={cn(
                  "absolute -right-10 -bottom-10 w-48 h-48 blur-2xl opacity-20 pointer-events-none",
                  isHighRisk ? "bg-rose-500" : "bg-indigo-500"
                )}
              />
              
              <div className="flex items-center gap-3 text-indigo-500 mb-4 relative z-10">
                <AlertOctagon size={24} />
                <h3 className="font-semibold tracking-wide">Trust Score</h3>
              </div>
              <p className="text-5xl font-black tracking-tighter text-slate-800 relative z-10">
                {data.trust_score}<span className="text-2xl text-slate-400">/100</span>
              </p>
              <div className="mt-4 inline-flex items-center gap-2 px-3 py-1.5 bg-slate-100 rounded-xl relative z-10">
                <span className="w-2 h-2 rounded-full bg-slate-400"></span>
                <p className="text-xs text-slate-600 font-semibold uppercase tracking-wider">{data.recent_failures} recent SLA breaches</p>
              </div>
            </motion.div>

          </div>
        </div>
      </motion.div>
    </div>
  );
}
