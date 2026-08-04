// ============================================================================
// DISEASE IDENTITY MAPPING — icon + color per disease.
//
// Keys are the EXACT lowercase values of the backend DiseaseCategory enum
// (app/health_risk/domain/disease_category.py): "dengue", "leptospirosis",
// "viral_fever". getDiseaseStyle() normalises case defensively because the
// backend emits lowercase and some test fixtures use uppercase.
//
// TO ADD A NEW DISEASE CATEGORY LATER: add a row to DiseaseCategory in the
// backend AND a matching entry in DISEASE_STYLES below — nothing else
// needs to change. Unknown or missing categories fall back to a neutral
// bell icon, which is also what SYSTEM alerts and other non-disease
// notifications get (they have no disease_category).
// ============================================================================

import { Bell, Bug, Droplets, Thermometer, type LucideIcon } from 'lucide-react';

export interface DiseaseStyle {
  icon: LucideIcon;
  color: string;
  badgeClass: string;
}

export const DISEASE_STYLES: Record<string, DiseaseStyle> = {
  dengue: {
    icon: Bug,
    color: '#e11d48',
    badgeClass: 'bg-rose-50',
  },
  leptospirosis: {
    icon: Droplets,
    color: '#0891b2',
    badgeClass: 'bg-cyan-50',
  },
  viral_fever: {
    icon: Thermometer,
    color: '#d97706',
    badgeClass: 'bg-amber-50',
  },
};

export const FALLBACK_DISEASE_STYLE: DiseaseStyle = {
  icon: Bell,
  color: '#64748b',
  badgeClass: 'bg-slate-50',
};

export function getDiseaseStyle(diseaseCategory: string | null | undefined): DiseaseStyle {
  if (!diseaseCategory) return FALLBACK_DISEASE_STYLE;
  return DISEASE_STYLES[diseaseCategory.toLowerCase()] ?? FALLBACK_DISEASE_STYLE;
}
