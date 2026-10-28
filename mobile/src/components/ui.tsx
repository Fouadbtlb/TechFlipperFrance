import { Ionicons } from '@expo/vector-icons';
import * as Haptics from 'expo-haptics';
import { useEffect, useState, type ComponentProps, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Animated,
  Pressable,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type TextProps,
  type TextStyle,
  type ViewStyle,
} from 'react-native';

import { font, radius, space, type as typo, usePalette, type Palette } from '@/lib/theme';

export type IconName = ComponentProps<typeof Ionicons>['name'];

type Variant = keyof typeof typo;
type Tone = 'text' | 'muted' | 'faint' | 'profit' | 'warn' | 'risk' | 'info' | 'brass' | 'accent' | 'onAccent';

function toneColor(p: Palette, t: Tone) {
  return {
    text: p.text,
    muted: p.textMuted,
    faint: p.textFaint,
    profit: p.profit,
    warn: p.warn,
    risk: p.risk,
    info: p.info,
    brass: p.brass,
    accent: p.accent,
    onAccent: p.onAccent,
  }[t];
}

export function T({ v = 'body', color = 'text', style, ...rest }: TextProps & { v?: Variant; color?: Tone }) {
  const p = usePalette();
  return <Text {...rest} style={[typo[v] as TextStyle, { color: toneColor(p, color) }, style]} />;
}

/** A hairline rule: the house divider, used instead of boxes. */
export function Rule({ style, brass }: { style?: StyleProp<ViewStyle>; brass?: boolean }) {
  const p = usePalette();
  return <View style={[{ height: StyleSheet.hairlineWidth, backgroundColor: brass ? p.brass : p.border }, style]} />;
}

export function Button({
  label,
  onPress,
  kind = 'primary',
  loading,
  disabled,
  style,
}: {
  label: string;
  onPress: () => void;
  kind?: 'primary' | 'secondary' | 'ghost';
  loading?: boolean;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const p = usePalette();
  const fg = kind === 'primary' ? p.onAccent : p.text;
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled || loading}
      onPress={() => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        onPress();
      }}
      style={({ pressed }) => [
        s.btn,
        kind === 'primary' && { backgroundColor: p.accent },
        kind === 'secondary' && { borderWidth: 1, borderColor: p.text },
        { opacity: disabled ? 0.4 : pressed ? 0.8 : 1 },
        style,
      ]}>
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <Text
          style={[
            typo.label,
            { color: fg, fontSize: 13, letterSpacing: 1.4 },
            kind === 'ghost' && { textDecorationLine: 'underline', textTransform: 'none', letterSpacing: 0.2, fontSize: 15 },
          ]}>
          {label}
        </Text>
      )}
    </Pressable>
  );
}

/** `soft`: for multi-select, where many chips are on at once and solid fills get heavy. */
export function Chip({ label, active, onPress, soft }: { label: string; active?: boolean; onPress: () => void; soft?: boolean }) {
  const p = usePalette();
  const bg = active ? (soft ? p.tint : p.accent) : 'transparent';
  const fg = active ? (soft ? p.accent : p.onAccent) : p.text;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: !!active }}
      onPress={() => {
        Haptics.selectionAsync();
        onPress();
      }}
      style={[s.chip, { borderColor: active ? p.accent : p.border, backgroundColor: bg }]}>
      <Text style={[typo.small, { fontFamily: font.sansMedium, color: fg }]}>{label}</Text>
    </Pressable>
  );
}

/** Text tabs with an underline, like a printed index. */
export function Tabs<K extends string>({
  options,
  value,
  onChange,
}: {
  options: { key: K; label: string }[];
  value: K;
  onChange: (k: K) => void;
}) {
  const p = usePalette();
  return (
    <View style={[s.tabs, { borderBottomColor: p.border }]}>
      {options.map((o) => {
        const on = o.key === value;
        return (
          <Pressable
            key={o.key}
            accessibilityRole="tab"
            accessibilityState={{ selected: on }}
            onPress={() => {
              Haptics.selectionAsync();
              onChange(o.key);
            }}
            style={[s.tab, on && { borderBottomColor: p.text }]}>
            <Text style={[typo.label, { color: on ? p.text : p.textFaint }]}>{o.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  const p = usePalette();
  return <View style={[s.card, { backgroundColor: p.surface, borderColor: p.border }, style]}>{children}</View>;
}

export function SectionTitle({ children, right }: { children: string; right?: ReactNode }) {
  return (
    <View style={s.sectionTitle}>
      <T v="label" color="brass">
        {children}
      </T>
      {right}
    </View>
  );
}

/** Label on the left, value on the right: the ledger line. */
export function LedgerRow({
  label,
  value,
  strong,
  tone,
}: {
  label: string;
  value: string;
  strong?: boolean;
  tone?: Tone;
}) {
  return (
    <View style={s.ledger}>
      <T v={strong ? 'strong' : 'body'} color={strong ? 'text' : 'muted'} style={{ flex: 1 }}>
        {label}
      </T>
      <T v={strong ? 'money' : 'strong'} color={tone ?? (strong ? 'profit' : 'text')} style={{ fontVariant: ['tabular-nums'] }}>
        {value}
      </T>
    </View>
  );
}

export function Pill({ label, tone = 'muted' }: { label: string; tone?: Tone }) {
  const p = usePalette();
  const c = toneColor(p, tone);
  return (
    <View style={[s.pill, { borderColor: c }]}>
      <Text style={[typo.label, { color: c, fontSize: 10.5, letterSpacing: 1.2 }]}>{label}</Text>
    </View>
  );
}

export function Skeleton({ h, w, style }: { h: number; w?: number | `${number}%`; style?: StyleProp<ViewStyle> }) {
  const p = usePalette();
  const [o] = useState(() => new Animated.Value(0.5));
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(o, { toValue: 1, duration: 800, useNativeDriver: true }),
        Animated.timing(o, { toValue: 0.5, duration: 800, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [o]);
  return (
    <Animated.View style={[{ height: h, width: w ?? '100%', borderRadius: radius.sm, backgroundColor: p.rule, opacity: o }, style]} />
  );
}

export function EmptyState({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <View style={s.empty}>
      <Rule brass style={{ width: 40, marginBottom: space.sm }} />
      <T v="h2" style={{ textAlign: 'center' }}>
        {title}
      </T>
      {body ? (
        <T color="muted" style={{ textAlign: 'center', maxWidth: 300 }}>
          {body}
        </T>
      ) : null}
      {action}
    </View>
  );
}

const s = StyleSheet.create({
  btn: {
    height: 52,
    borderRadius: radius.md,
    paddingHorizontal: space.xl,
    alignItems: 'center',
    justifyContent: 'center',
  },
  chip: {
    height: 34,
    paddingHorizontal: 14,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
    justifyContent: 'center',
  },
  tabs: { flexDirection: 'row', gap: space.xl, borderBottomWidth: StyleSheet.hairlineWidth },
  tab: { paddingBottom: 10, borderBottomWidth: 2, borderBottomColor: 'transparent', marginBottom: -StyleSheet.hairlineWidth },
  card: { borderRadius: radius.lg, borderWidth: StyleSheet.hairlineWidth, padding: space.lg },
  sectionTitle: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: space.md,
    marginTop: space.xxl,
  },
  ledger: { flexDirection: 'row', alignItems: 'baseline', gap: space.md, paddingVertical: 6 },
  pill: {
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: 6,
    paddingVertical: 2,
    alignSelf: 'flex-start',
  },
  empty: { alignItems: 'center', justifyContent: 'center', gap: space.md, padding: space.xxl, flex: 1 },
});
