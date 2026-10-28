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

import { radius, space, type as typo, usePalette } from '@/lib/theme';

export type IconName = ComponentProps<typeof Ionicons>['name'];

type Variant = keyof typeof typo;

export function T({
  v = 'body',
  color,
  style,
  ...rest
}: TextProps & { v?: Variant; color?: 'text' | 'muted' | 'faint' | 'profit' | 'warn' | 'risk' | 'onAccent' | 'info' }) {
  const p = usePalette();
  const c = {
    text: p.text,
    muted: p.textMuted,
    faint: p.textFaint,
    profit: p.profit,
    warn: p.warn,
    risk: p.risk,
    onAccent: p.onAccent,
    info: p.info,
  }[color ?? 'text'];
  return <Text {...rest} style={[typo[v] as TextStyle, { color: c }, style]} />;
}

export function Button({
  label,
  onPress,
  kind = 'primary',
  icon,
  loading,
  disabled,
  style,
}: {
  label: string;
  onPress: () => void;
  kind?: 'primary' | 'secondary' | 'ghost';
  icon?: IconName;
  loading?: boolean;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const p = usePalette();
  const bg = kind === 'primary' ? p.profit : kind === 'secondary' ? p.elevated : 'transparent';
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
        { backgroundColor: bg, opacity: disabled ? 0.4 : pressed ? 0.85 : 1 },
        kind === 'secondary' && { borderWidth: StyleSheet.hairlineWidth, borderColor: p.border },
        style,
      ]}>
      {loading ? (
        <ActivityIndicator color={fg} />
      ) : (
        <>
          {icon ? <Ionicons name={icon} size={18} color={fg} /> : null}
          <Text style={[typo.body, { color: fg, fontWeight: '700' }]}>{label}</Text>
        </>
      )}
    </Pressable>
  );
}

export function Chip({
  label,
  active,
  onPress,
  icon,
}: {
  label: string;
  active?: boolean;
  onPress: () => void;
  icon?: IconName;
}) {
  const p = usePalette();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: !!active }}
      onPress={() => {
        Haptics.selectionAsync();
        onPress();
      }}
      style={[
        s.chip,
        {
          backgroundColor: active ? p.text : p.surface,
          borderColor: active ? p.text : p.border,
        },
      ]}>
      {icon ? <Ionicons name={icon} size={14} color={active ? p.bg : p.textMuted} /> : null}
      <Text style={[typo.small, { color: active ? p.bg : p.text, fontWeight: '600' }]}>{label}</Text>
    </Pressable>
  );
}

export function Segmented<K extends string>({
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
    <View style={[s.seg, { backgroundColor: p.surface, borderColor: p.border }]}>
      {options.map((o) => {
        const on = o.key === value;
        return (
          <Pressable
            key={o.key}
            accessibilityRole="button"
            accessibilityState={{ selected: on }}
            onPress={() => {
              Haptics.selectionAsync();
              onChange(o.key);
            }}
            style={[s.segItem, on && { backgroundColor: p.elevated }]}>
            <Text style={[typo.small, { color: on ? p.text : p.textMuted, fontWeight: on ? '700' : '600' }]}>
              {o.label}
            </Text>
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
      <T v="tiny" color="muted" style={{ textTransform: 'uppercase' }}>
        {children}
      </T>
      {right}
    </View>
  );
}

export function Pill({
  label,
  tone = 'neutral',
  icon,
}: {
  label: string;
  tone?: 'neutral' | 'profit' | 'warn' | 'risk' | 'info';
  icon?: IconName;
}) {
  const p = usePalette();
  const map = {
    neutral: [p.elevated, p.textMuted],
    profit: [p.profitSoft, p.profit],
    warn: [p.warnSoft, p.warn],
    risk: [p.riskSoft, p.risk],
    info: [p.elevated, p.info],
  } as const;
  const [bg, fg] = map[tone];
  return (
    <View style={[s.pill, { backgroundColor: bg }]}>
      {icon ? <Ionicons name={icon} size={12} color={fg} /> : null}
      <Text style={[typo.tiny, { color: fg }]}>{label}</Text>
    </View>
  );
}

export function Skeleton({ h, w, r = radius.md, style }: { h: number; w?: number | `${number}%`; r?: number; style?: StyleProp<ViewStyle> }) {
  const p = usePalette();
  const [o] = useState(() => new Animated.Value(0.5));
  useEffect(() => {
    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(o, { toValue: 1, duration: 700, useNativeDriver: true }),
        Animated.timing(o, { toValue: 0.5, duration: 700, useNativeDriver: true }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [o]);
  return <Animated.View style={[{ height: h, width: w ?? '100%', borderRadius: r, backgroundColor: p.elevated, opacity: o }, style]} />;
}

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon: IconName;
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  const p = usePalette();
  return (
    <View style={s.empty}>
      <View style={[s.emptyIcon, { backgroundColor: p.surface, borderColor: p.border }]}>
        <Ionicons name={icon} size={28} color={p.textMuted} />
      </View>
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
    borderRadius: radius.lg,
    paddingHorizontal: space.xl,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.sm,
  },
  chip: {
    height: 34,
    paddingHorizontal: 14,
    borderRadius: radius.pill,
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  seg: {
    flexDirection: 'row',
    padding: 3,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
  },
  segItem: { flex: 1, height: 32, borderRadius: radius.sm, alignItems: 'center', justifyContent: 'center' },
  card: { borderRadius: radius.lg, borderWidth: StyleSheet.hairlineWidth, padding: space.lg },
  sectionTitle: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: space.sm,
    marginTop: space.xl,
  },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 8,
    height: 22,
    borderRadius: radius.pill,
    alignSelf: 'flex-start',
  },
  empty: { alignItems: 'center', justifyContent: 'center', gap: space.md, padding: space.xxl, flex: 1 },
  emptyIcon: {
    width: 64,
    height: 64,
    borderRadius: 32,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    marginBottom: space.sm,
  },
});
