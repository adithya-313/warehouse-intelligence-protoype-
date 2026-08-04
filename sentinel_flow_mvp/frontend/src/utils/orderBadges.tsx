import React from 'react';
import { Clock, CheckCircle, AlertTriangle } from 'lucide-react';

export const getStatusBadge = (status: string) => {
  switch (status) {
    case 'FULFILLED':
      return <span className="flex items-center gap-1 px-3 py-1 bg-green-100 text-green-700 rounded-full text-xs font-bold"><CheckCircle size={14} /> FULFILLED</span>;
    case 'SUBMITTED':
      return <span className="flex items-center gap-1 px-3 py-1 bg-blue-100 text-blue-700 rounded-full text-xs font-bold"><Clock size={14} /> IN TRANSIT</span>;
    default:
      return <span className="flex items-center gap-1 px-3 py-1 bg-slate-100 text-slate-700 rounded-full text-xs font-bold"><AlertTriangle size={14} /> {status}</span>;
  }
};

export const getDelayBadge = (daysLate: number) => {
  if (daysLate <= 0) return null;
  if (daysLate >= 7) {
    return <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-red-100 text-red-700 font-bold border border-red-200">• {daysLate} days late</span>;
  } else if (daysLate >= 3) {
    return <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-red-50 text-red-600 font-medium border border-red-100">• {daysLate} days late</span>;
  } else {
    return <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-orange-50 text-orange-600 font-medium border border-orange-100">• {daysLate} {daysLate === 1 ? 'day' : 'days'} late</span>;
  }
};
