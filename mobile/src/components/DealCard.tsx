import { Image } from 'expo-image';
import { router } from 'expo-router';
import { memo } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { ago, euros, km, signedEuros } from '@/lib/format';
import { radius, space, usePalette } from '@/lib/theme';
import type { DealCard as Deal } from '@/lib/types';
import { useNow } from '@/lib/useNow';

import { Pill, T } from './ui';

/** One line of the ledger: the photo, what it is, and what it leaves you. */
function DealCardBase({ deal, compact = false }: { deal: Deal; compact?: boolean }) {
  const p = usePalette();
  const now = useNow();
  const drop = deal.prev_price ? deal.prev_price - deal.price : 0;
  // Real first-seen time, never invented urgency: good deals go in minutes.
  const fresh = !!deal.first_seen && now - Date.parse(deal.first_seen) < 30 * 60_000;
  const where = deal.mode === 'ship' ? 'Envoi' : km(deal.distance_km);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${deal.title}, bénéfice ${signedEuros(deal.net)}`}
      onPress={() => router.push({ pathname: '/deal/[uid]', params: { uid: deal.uid } })}
      style={({ pressed }) => [
        s.row,
        compact && [s.compact, { backgroundColor: p.surface, borderColor: p.border }],
        { opacity: deal.gone ? 0.5 : pressed ? 0.75 : 1 },
      ]}>
      <Image
        source={deal.thumb ? { uri: deal.thumb } : null}
        style={[s.thumb, { backgroundColor: p.rule }, compact && s.thumbCompact]}
        contentFit="cover"
        transition={150}
        recyclingKey={deal.uid}
      />

      <View style={s.body}>
        <T v="strong" numberOfLines={2} style={{ lineHeight: 21 }}>
          {deal.title}
        </T>
        <T v="small" color="muted" numberOfLines={1} style={{ fontVariant: ['tabular-nums'] }}>
          {euros(deal.price)} · {where}
          {!compact && deal.city ? ` · ${deal.city}` : ''}
        </T>
        {!compact &&
        (fresh || drop > 0 || deal.reposts > 0 || deal.risk !== 'low' || deal.gone || deal.shop || deal.carrier_locked || deal.photo_unverified) ? (
          <View style={s.pills}>
            {fresh ? <Pill tone="brass" label="Nouveau" /> : null}
            {deal.shop ? <Pill tone="info" label="Magasin" /> : null}
            {deal.carrier_locked ? <Pill tone="warn" label="Bloqué opérateur" /> : null}
            {deal.photo_unverified ? <Pill tone="warn" label="Photo à contrôler" /> : null}
            {drop > 0 ? <Pill tone="profit" label={`Baisse de ${euros(drop)}`} /> : null}
            {deal.reposts > 0 ? <Pill tone="info" label="Remise en ligne" /> : null}
            {deal.risk === 'high' ? <Pill tone="risk" label="Prudence" /> : null}
            {deal.risk === 'medium' ? <Pill tone="warn" label="Vigilance" /> : null}
            {deal.gone ? <Pill label="Plus disponible" /> : null}
          </View>
        ) : null}
      </View>

      <View style={s.right}>
        <T v="money" color="profit" style={{ fontVariant: ['tabular-nums'] }}>
          {signedEuros(deal.net)}
        </T>
        {!compact ? (
          <T v="small" color="faint">
            {ago(deal.first_seen, now)}
          </T>
        ) : null}
      </View>
    </Pressable>
  );
}

export const DealCard = memo(DealCardBase);

const s = StyleSheet.create({
  row: { flexDirection: 'row', gap: space.md, paddingVertical: space.lg, alignItems: 'flex-start' },
  compact: {
    width: 310,
    paddingHorizontal: space.md,
    paddingVertical: space.md,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
  },
  thumb: { width: 76, height: 76, borderRadius: radius.sm },
  thumbCompact: { width: 60, height: 60 },
  body: { flex: 1, gap: 4 },
  right: { alignItems: 'flex-end', gap: 2, minWidth: 72 },
  pills: { flexDirection: 'row', gap: 6, flexWrap: 'wrap', marginTop: 4 },
});
