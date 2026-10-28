import type { Category } from './types';

const eur = new Intl.NumberFormat('fr-FR', { maximumFractionDigits: 0 });

// Non-breaking space before units: "142 €" never wraps onto two lines.
export const euros = (n: number | null | undefined) => (n == null ? '—' : `${eur.format(Math.round(n))}\u00a0€`);
export const signedEuros = (n: number | null | undefined) =>
  n == null ? '—' : `${n >= 0 ? '+' : '−'}${eur.format(Math.abs(Math.round(n)))}\u00a0€`;

export function km(d: number | null | undefined) {
  if (d == null) return 'Distance inconnue';
  if (d < 1) return '<\u00a01\u00a0km';
  return `${Math.round(d)}\u00a0km`;
}

export function ago(iso: string | null | undefined, now: number = Date.now()) {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  const m = Math.max(0, Math.round((now - t) / 60000));
  if (m < 1) return "à l’instant";
  if (m < 60) return `il y a ${m} min`;
  const h = Math.round(m / 60);
  if (h < 24) return `il y a ${h} h`;
  const d = Math.round(h / 24);
  return d === 1 ? 'hier' : `il y a ${d} j`;
}

export const CATEGORY_LABEL: Record<Category, string> = {
  console: 'Consoles',
  pc: 'PC',
  gpu: 'Cartes graphiques',
  cpu: 'Processeurs',
  laptop: 'Portables',
  phone: 'Téléphones',
  monitor: 'Écrans',
  parts: 'Composants',
  accessory: 'Accessoires',
  other: 'Autre',
};

export const CATEGORY_ICON: Record<Category, string> = {
  console: 'game-controller-outline',
  pc: 'desktop-outline',
  gpu: 'hardware-chip-outline',
  cpu: 'hardware-chip-outline',
  laptop: 'laptop-outline',
  phone: 'phone-portrait-outline',
  monitor: 'tv-outline',
  parts: 'construct-outline',
  accessory: 'headset-outline',
  other: 'cube-outline',
};
