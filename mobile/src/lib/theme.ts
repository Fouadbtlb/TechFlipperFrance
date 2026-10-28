import { useColorScheme } from 'react-native';

// "Old money": ivory paper, racing green, brass, oxblood. Quiet surfaces, thin
// rules instead of boxes, a serif for anything that carries weight (titles,
// money) and a humanist sans for the working text. Color is spent sparingly:
// green means money, brass means distinction, oxblood means caution.

const light = {
  bg: '#F3EEE4',
  surface: '#FAF7F0',
  elevated: '#FFFDF8',
  border: '#DCD3C1',
  rule: '#E6DECF',
  text: '#1C2620',
  textMuted: '#5F6358',
  textFaint: '#9A9585',
  accent: '#1F3B2D', // racing green: primary actions
  onAccent: '#F6F1E6',
  brass: '#9A7B3F',
  profit: '#2B5B3C',
  warn: '#8C6418',
  risk: '#7B2D33',
  info: '#2C4264',
  overlay: 'rgba(20,24,20,0.45)',
  tint: 'rgba(31,59,45,0.06)',
};

const dark: typeof light = {
  bg: '#111813',
  surface: '#172019',
  elevated: '#1D2820',
  border: '#2E3B31',
  rule: '#243028',
  text: '#ECE5D5',
  textMuted: '#A7A08C',
  textFaint: '#6E6B5E',
  accent: '#C9AE72', // brass carries the primary action at night
  onAccent: '#14201A',
  brass: '#C9AE72',
  profit: '#A3C7A6',
  warn: '#D3A65A',
  risk: '#C98079',
  info: '#9DB1CF',
  overlay: 'rgba(0,0,0,0.55)',
  tint: 'rgba(201,174,114,0.07)',
};

export type Palette = typeof light;

export function usePalette(): Palette {
  return useColorScheme() === 'dark' ? dark : light;
}

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };
// Restrained corners: paper and leather, not bubbles.
export const radius = { sm: 2, md: 4, lg: 6 };

// Loaded in the root layout (see useAppFonts).
export const font = {
  serif: 'EBGaramond_500Medium',
  serifBold: 'EBGaramond_600SemiBold',
  sans: 'SourceSans3_400Regular',
  sansMedium: 'SourceSans3_500Medium',
  sansBold: 'SourceSans3_600SemiBold',
};

export const type = {
  hero: { fontFamily: font.serif, fontSize: 52, lineHeight: 56, letterSpacing: -0.5 },
  title: { fontFamily: font.serif, fontSize: 34, lineHeight: 38, letterSpacing: -0.3 },
  h2: { fontFamily: font.serifBold, fontSize: 22, lineHeight: 27 },
  money: { fontFamily: font.serifBold, fontSize: 24, lineHeight: 28 },
  body: { fontFamily: font.sans, fontSize: 16, lineHeight: 22 },
  strong: { fontFamily: font.sansBold, fontSize: 16, lineHeight: 22 },
  small: { fontFamily: font.sans, fontSize: 14, lineHeight: 19 },
  // small capitals, the house style for labels
  label: { fontFamily: font.sansBold, fontSize: 11.5, lineHeight: 15, letterSpacing: 1.6, textTransform: 'uppercase' as const },
};

export function zoneColor(p: Palette, zone: string) {
  return zone === 'EASY' ? p.profit : zone === 'MEDIUM' ? p.brass : p.info;
}
