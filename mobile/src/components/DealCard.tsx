import { Ionicons } from '@expo/vector-icons';
import { Image } from 'expo-image';
import { router } from 'expo-router';
import { memo } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { ago, euros, km, signedEuros } from '@/lib/format';
import { radius, space, usePalette, zoneColor } from '@/lib/theme';
import type { DealCard as Deal } from '@/lib/types';

import { Pill, T } from './ui';

function DealCardBase({ deal, compact = false }: { deal: Deal; compact?: boolean }) {
  const p = usePalette();
  const drop = deal.prev_price ? deal.prev_price - deal.price : 0;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${deal.title}, bénéfice ${signedEuros(deal.net)}`}
      onPress={() => router.push({ pathname: '/deal/[uid]', params: { uid: deal.uid } })}
      style={({ pressed }) => [
        s.card,
        { backgroundColor: p.surface, borderColor: p.border, opacity: deal.gone ? 0.5 : pressed ? 0.9 : 1 },
        compact && s.compact,
      ]}>
      <View>
        <Image
          source={deal.thumb ? { uri: deal.thumb } : null}
          style={[s.thumb, { backgroundColor: p.elevated }, compact && s.thumbCompact]}
          contentFit="cover"
          transition={150}
          recyclingKey={deal.uid}
        />
        <View style={[s.zoneDot, { backgroundColor: zoneColor(p, deal.zone), borderColor: p.surface }]} />
      </View>

      <View style={s.body}>
        <View style={s.topRow}>
          <T v="h2" color="profit" style={s.num}>
            {signedEuros(deal.net)}
          </T>
          {deal.risk !== 'low' ? (
            <Ionicons
              name="alert-circle"
              size={18}
              color={deal.risk === 'high' ? p.risk : p.warn}
              accessibilityLabel="Points de vigilance"
            />
          ) : null}
        </View>

        <T numberOfLines={compact ? 1 : 2} style={{ fontWeight: '600' }}>
          {deal.title}
        </T>

        <View style={s.meta}>
          <T v="small" color="muted" style={s.num}>
            {euros(deal.price)}
          </T>
          <T v="small" color="faint">·</T>
          <Ionicons name={deal.mode === 'ship' ? 'cube-outline' : 'navigate-outline'} size={12} color={p.textMuted} />
          <T v="small" color="muted">
            {deal.mode === 'ship' ? 'Envoi' : km(deal.distance_km)}
          </T>
          {!compact ? (
            <>
              <T v="small" color="faint">·</T>
              <T v="small" color="muted" numberOfLines={1} style={{ flexShrink: 1 }}>
                {ago(deal.first_seen)}
              </T>
            </>
          ) : null}
        </View>

        {drop > 0 && !compact ? <Pill tone="profit" icon="trending-down" label={`Baisse de ${euros(drop)}`} /> : null}
        {deal.gone ? <Pill label="Plus disponible" /> : null}
      </View>
    </Pressable>
  );
}

export const DealCard = memo(DealCardBase);

const s = StyleSheet.create({
  card: {
    flexDirection: 'row',
    gap: space.md,
    padding: space.md,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
  },
  compact: { width: 300 },
  thumb: { width: 96, height: 96, borderRadius: radius.md },
  thumbCompact: { width: 76, height: 76 },
  zoneDot: {
    position: 'absolute',
    top: 6,
    left: 6,
    width: 12,
    height: 12,
    borderRadius: 6,
    borderWidth: 2,
  },
  body: { flex: 1, gap: 4, justifyContent: 'center' },
  topRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  meta: { flexDirection: 'row', alignItems: 'center', gap: 5 },
  num: { fontVariant: ['tabular-nums'] },
});
