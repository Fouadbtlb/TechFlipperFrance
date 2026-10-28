import { useColorScheme } from 'react-native';

// One accent (profit green) carries meaning; everything else stays quiet so the
// numbers that matter are the loudest thing on screen.
const dark = {
  bg: '#0B0D10',
  surface: '#14171C',
  elevated: '#1B1F26',
  border: '#262B33',
  text: '#F2F4F7',
  textMuted: '#8B94A3',
  textFaint: '#5B6371',
  profit: '#2BD576',
  profitSoft: 'rgba(43,213,118,0.14)',
  warn: '#FFB547',
  warnSoft: 'rgba(255,181,71,0.14)',
  risk: '#FF6B6B',
  riskSoft: 'rgba(255,107,107,0.14)',
  info: '#6EA8FF',
  onAccent: '#04140A',
  overlay: 'rgba(0,0,0,0.55)',
};

const light: typeof dark = {
  bg: '#F6F7F9',
  surface: '#FFFFFF',
  elevated: '#FFFFFF',
  border: '#E4E7EC',
  text: '#0E1116',
  textMuted: '#5D6676',
  textFaint: '#98A1B0',
  profit: '#0FA958',
  profitSoft: 'rgba(15,169,88,0.10)',
  warn: '#C27803',
  warnSoft: 'rgba(194,120,3,0.10)',
  risk: '#D93F3F',
  riskSoft: 'rgba(217,63,63,0.10)',
  info: '#2F6FDB',
  onAccent: '#FFFFFF',
  overlay: 'rgba(0,0,0,0.35)',
};

export type Palette = typeof dark;

export function usePalette(): Palette {
  return useColorScheme() === 'light' ? light : dark;
}

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };
export const radius = { sm: 8, md: 12, lg: 16, xl: 22, pill: 999 };

export const type = {
  hero: { fontSize: 44, fontWeight: '800' as const, letterSpacing: -1.2 },
  title: { fontSize: 28, fontWeight: '800' as const, letterSpacing: -0.6 },
  h2: { fontSize: 20, fontWeight: '700' as const, letterSpacing: -0.3 },
  body: { fontSize: 15, fontWeight: '500' as const },
  small: { fontSize: 13, fontWeight: '500' as const },
  tiny: { fontSize: 11, fontWeight: '600' as const, letterSpacing: 0.4 },
  num: { fontVariant: ['tabular-nums' as const] },
};

export function zoneColor(p: Palette, zone: string) {
  return zone === 'EASY' ? p.profit : zone === 'MEDIUM' ? p.warn : p.info;
}
