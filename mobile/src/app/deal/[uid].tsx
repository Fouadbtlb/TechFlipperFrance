import { Ionicons } from '@expo/vector-icons';
import { Image } from 'expo-image';
import * as Haptics from 'expo-haptics';
import { router, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { ActionSheetIOS, Alert, FlatList, Platform, Pressable, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Button, Card, EmptyState, Pill, SectionTitle, Skeleton, T } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { ago, euros, km, signedEuros } from '@/lib/format';
import { useDeal, useHide, useToggleSave } from '@/lib/queries';
import { radius, space, usePalette, zoneColor } from '@/lib/theme';
import type { DealDetail, Part } from '@/lib/types';

const SOURCE_LABEL: Record<Part['source'], string> = {
  learned: 'prix marché',
  blend: 'marché + estimation',
  seed: 'estimation',
  ai: 'estimation IA',
  unknown: 'non chiffré',
};

export default function DealScreen() {
  const { uid } = useLocalSearchParams<{ uid: string }>();
  const p = usePalette();
  const insets = useSafeAreaInsets();
  const q = useDeal(uid);
  const save = useToggleSave(uid);
  const hide = useHide(uid);

  function more() {
    const run = (i: number) => {
      if (i === 0) hide.mutate('sold', { onSuccess: () => router.back() });
      if (i === 1) hide.mutate('not_interested', { onSuccess: () => router.back() });
    };
    const options = ['Déjà vendu', 'Pas intéressé', 'Annuler'];
    if (Platform.OS === 'ios') {
      ActionSheetIOS.showActionSheetWithOptions({ options, cancelButtonIndex: 2, destructiveButtonIndex: 0 }, run);
    } else {
      Alert.alert('Masquer cette annonce', undefined, [
        { text: options[0], onPress: () => run(0) },
        { text: options[1], onPress: () => run(1) },
        { text: options[2], style: 'cancel' },
      ]);
    }
  }

  const d = q.data;
  return (
    <View style={{ flex: 1, backgroundColor: p.bg }}>
      {q.isLoading ? (
        <View style={{ padding: space.lg, paddingTop: insets.top + 60, gap: space.md }}>
          <Skeleton h={280} />
          <Skeleton h={60} w="60%" />
          <Skeleton h={140} />
        </View>
      ) : q.isError || !d ? (
        <EmptyState
          icon={q.error instanceof ApiError && q.error.status === 429 ? 'hourglass-outline' : 'alert-circle-outline'}
          title={q.error instanceof ApiError && q.error.status === 404 ? 'Annonce introuvable' : 'Chargement impossible'}
          body={q.error instanceof ApiError ? q.error.message : undefined}
          action={<Button label="Retour" kind="secondary" onPress={() => router.back()} />}
        />
      ) : (
        <Detail d={d} bottomPad={insets.bottom + 96} />
      )}

      {/* floating header */}
      <View style={[s.header, { top: insets.top + 6 }]} pointerEvents="box-none">
        <RoundButton icon="chevron-back" label="Retour" onPress={() => router.back()} />
        {d ? <RoundButton icon="ellipsis-horizontal" label="Plus d'options" onPress={more} /> : null}
      </View>

      {d ? (
        <View style={[s.bar, { paddingBottom: insets.bottom + space.md, backgroundColor: p.bg, borderTopColor: p.border }]}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={d.saved ? 'Retirer des favoris' : 'Ajouter aux favoris'}
            onPress={() => {
              Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
              save.mutate(!d.saved);
            }}
            style={[s.save, { backgroundColor: p.surface, borderColor: p.border }]}>
            <Ionicons name={d.saved ? 'heart' : 'heart-outline'} size={22} color={d.saved ? p.risk : p.text} />
          </Pressable>
          <Button
            label={`Voir sur ${d.source === '2ememain' ? '2ememain' : 'Leboncoin'}`}
            icon="open-outline"
            onPress={() => WebBrowser.openBrowserAsync(d.url)}
            style={{ flex: 1 }}
          />
        </View>
      ) : null}
    </View>
  );
}

function RoundButton({ icon, label, onPress }: { icon: any; label: string; onPress: () => void }) {
  const p = usePalette();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      hitSlop={8}
      style={[s.round, { backgroundColor: p.overlay }]}>
      <Ionicons name={icon} size={20} color="#fff" />
    </Pressable>
  );
}

function Detail({ d, bottomPad }: { d: DealDetail; bottomPad: number }) {
  const p = usePalette();
  const { width } = useWindowDimensions();
  const [page, setPage] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const drop = d.prev_price ? d.prev_price - d.price : 0;
  const maxPart = Math.max(1, ...d.parts.map((x) => x.value ?? 0));
  const partsTotal = d.parts.reduce((sum, x) => sum + (x.value ?? 0), 0);
  const sellerFlags = d.seller?.flags ?? [];

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: bottomPad }}>
      {/* photos */}
      <View>
        {d.images.length ? (
          <FlatList
            data={d.images}
            horizontal
            pagingEnabled
            showsHorizontalScrollIndicator={false}
            keyExtractor={(u, i) => `${i}-${u}`}
            onMomentumScrollEnd={(e) => setPage(Math.round(e.nativeEvent.contentOffset.x / width))}
            renderItem={({ item }) => (
              <Image source={{ uri: item }} style={{ width, height: width * 0.85, backgroundColor: p.elevated }} contentFit="cover" transition={150} />
            )}
          />
        ) : (
          <View style={{ width, height: width * 0.6, backgroundColor: p.elevated }} />
        )}
        {d.images.length > 1 ? (
          <View style={s.dots}>
            {d.images.map((_, i) => (
              <View key={i} style={[s.dot, { backgroundColor: i === page ? '#fff' : 'rgba(255,255,255,0.45)' }]} />
            ))}
          </View>
        ) : null}
      </View>

      <View style={{ padding: space.lg }}>
        {/* hero */}
        <View style={s.heroRow}>
          <T v="hero" color="profit" style={{ fontVariant: ['tabular-nums'] }}>
            {signedEuros(d.net)}
          </T>
          <View style={[s.zone, { borderColor: zoneColor(p, d.zone) }]}>
            <T v="tiny" style={{ color: zoneColor(p, d.zone) }}>
              {d.mode === 'ship' ? 'ENVOI' : km(d.distance_km).toUpperCase()}
            </T>
          </View>
        </View>
        <T v="small" color="muted">
          Bénéfice net estimé après {d.mode === 'ship' ? "frais d'envoi" : 'trajet'}
        </T>
        <T v="h2" style={{ marginTop: space.md }}>
          {d.title}
        </T>
        <View style={s.metaRow}>
          <Ionicons name="location-outline" size={13} color={p.textMuted} />
          <T v="small" color="muted">
            {[d.city, d.department].filter(Boolean).join(', ') || '—'}
          </T>
          <T v="small" color="faint">·</T>
          <T v="small" color="muted">
            {ago(d.first_seen)}
          </T>
          {d.condition ? (
            <>
              <T v="small" color="faint">·</T>
              <T v="small" color="muted">
                {d.condition}
              </T>
            </>
          ) : null}
        </View>
        {drop > 0 ? (
          <View style={{ marginTop: space.sm }}>
            <Pill tone="profit" icon="trending-down" label={`Baisse de ${euros(drop)} (était ${euros(d.prev_price)})`} />
          </View>
        ) : null}

        {/* the math */}
        <SectionTitle>Le calcul</SectionTitle>
        <Card style={{ gap: space.sm }}>
          <MathRow label="Revente estimée" value={euros(d.value)} />
          <MathRow label="Prix demandé" value={`− ${euros(d.price)}`} />
          <MathRow
            label={d.mode === 'ship' ? 'Envoi' : `Trajet aller-retour (${km(d.distance_km)})`}
            value={`− ${euros(d.logistics)}`}
          />
          <View style={[s.rule, { backgroundColor: p.border }]} />
          <MathRow label="Ce qu'il te reste" value={signedEuros(d.net)} strong />
        </Card>

        {/* parts */}
        {d.parts.length ? (
          <>
            <SectionTitle>{d.parts.length > 1 ? 'Valeur pièce par pièce' : 'Valeur de revente'}</SectionTitle>
            <Card style={{ gap: space.md }}>
              {d.parts.map((part, i) => (
                <View key={`${part.label}-${i}`} style={{ gap: 6 }}>
                  <View style={s.partHead}>
                    <T style={{ fontWeight: '600', flex: 1 }} numberOfLines={1}>
                      {part.label}
                      {part.qty > 1 ? ` ×${part.qty}` : ''}
                    </T>
                    <T style={{ fontWeight: '700', fontVariant: ['tabular-nums'] }}>{euros(part.value)}</T>
                  </View>
                  <View style={[s.track, { backgroundColor: p.elevated }]}>
                    <View
                      style={[s.fill, { width: `${Math.round(((part.value ?? 0) / maxPart) * 100)}%`, backgroundColor: p.profit }]}
                    />
                  </View>
                  <T v="tiny" color="faint">
                    {SOURCE_LABEL[part.source]}
                    {part.source === 'learned' || part.source === 'blend' ? ` · ${part.n} annonces comparées` : ''}
                    {part.condition !== 'working' ? ' · état dégradé' : ''}
                  </T>
                </View>
              ))}
              {partsTotal > d.value + 1 ? (
                <>
                  <View style={[s.rule, { backgroundColor: p.border }]} />
                  <MathRow label="Total au prix du marché" value={euros(partsTotal)} />
                  <MathRow label="Décote revente rapide" value={`− ${euros(partsTotal - d.value)}`} />
                  <T v="tiny" color="faint">
                    Ce qu’on perd en vendant vite, selon la catégorie (une console part au prix, une alim se brade).
                  </T>
                </>
              ) : null}
            </Card>
          </>
        ) : null}

        {/* trust */}
        <SectionTitle>Confiance</SectionTitle>
        <Card style={{ gap: space.md }}>
          <TrustRow
            icon="analytics-outline"
            label="Fiabilité du prix"
            value={`${Math.round((d.confidence ?? 0) * 100)}%`}
            tone={(d.confidence ?? 0) >= 0.6 ? 'profit' : (d.confidence ?? 0) >= 0.3 ? 'warn' : 'risk'}
          />
          <TrustRow
            icon="camera-outline"
            label="Photos vérifiées par IA"
            value={d.photo_checked ? 'Oui' : 'Non'}
            tone={d.photo_checked ? 'profit' : 'muted'}
          />
          {d.scam_score != null ? (
            <TrustRow
              icon="shield-checkmark-outline"
              label="Risque d'arnaque"
              value={`${Math.round(d.scam_score)}/10`}
              tone={d.scam_score >= 6 ? 'risk' : d.scam_score >= 3 ? 'warn' : 'profit'}
            />
          ) : null}
          {d.seller?.known ? (
            <TrustRow
              icon="person-outline"
              label={`Vendeur ${d.seller.kind ?? ''}`.trim()}
              value={[
                d.seller.age_days != null ? (d.seller.age_days >= 365 ? `${Math.floor(d.seller.age_days / 365)} an(s)` : `${d.seller.age_days} j`) : null,
                d.seller.rating != null && d.seller.reviews ? `★ ${d.seller.rating.toFixed(1)} (${d.seller.reviews})` : null,
              ]
                .filter(Boolean)
                .join(' · ') || '—'}
              tone="muted"
            />
          ) : null}
          {sellerFlags.map((f) => (
            <View key={f.text} style={s.flag}>
              <Ionicons name="alert-circle" size={16} color={f.level === 'risk' ? p.risk : p.warn} />
              <T v="small" color={f.level === 'risk' ? 'risk' : 'warn'} style={{ flex: 1 }}>
                {f.text}
              </T>
            </View>
          ))}
          {!d.shippable && d.mode === 'pickup' ? (
            <View style={s.flag}>
              <Ionicons name="hand-left-outline" size={16} color={p.textMuted} />
              <T v="small" color="muted" style={{ flex: 1 }}>
                Remise en main propre uniquement : vérifie et teste sur place.
              </T>
            </View>
          ) : null}
        </Card>

        {/* description */}
        {d.description ? (
          <>
            <SectionTitle>Description</SectionTitle>
            <Pressable onPress={() => setExpanded((x) => !x)}>
              <T color="muted" numberOfLines={expanded ? undefined : 5} style={{ lineHeight: 22 }}>
                {d.description}
              </T>
              <T v="small" style={{ marginTop: 6, fontWeight: '700' }}>
                {expanded ? 'Réduire' : 'Lire la suite'}
              </T>
            </Pressable>
          </>
        ) : null}
      </View>
    </ScrollView>
  );
}

function MathRow({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <View style={s.mathRow}>
      <T color={strong ? 'text' : 'muted'} style={strong ? { fontWeight: '700' } : undefined}>
        {label}
      </T>
      <T
        color={strong ? 'profit' : 'text'}
        style={{ fontWeight: strong ? '800' : '600', fontVariant: ['tabular-nums'], fontSize: strong ? 18 : 15 }}>
        {value}
      </T>
    </View>
  );
}

function TrustRow({
  icon,
  label,
  value,
  tone,
}: {
  icon: any;
  label: string;
  value: string;
  tone: 'profit' | 'warn' | 'risk' | 'muted';
}) {
  const p = usePalette();
  return (
    <View style={s.mathRow}>
      <View style={{ flexDirection: 'row', gap: space.sm, alignItems: 'center', flex: 1 }}>
        <Ionicons name={icon} size={17} color={p.textMuted} />
        <T>{label}</T>
      </View>
      <T color={tone} style={{ fontWeight: '700' }}>
        {value}
      </T>
    </View>
  );
}

const s = StyleSheet.create({
  header: { position: 'absolute', left: space.lg, right: space.lg, flexDirection: 'row', justifyContent: 'space-between' },
  round: { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center' },
  dots: { position: 'absolute', bottom: 12, alignSelf: 'center', flexDirection: 'row', gap: 6 },
  dot: { width: 6, height: 6, borderRadius: 3 },
  heroRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  zone: { borderWidth: 1.5, borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 4 },
  metaRow: { flexDirection: 'row', alignItems: 'center', gap: 5, marginTop: 6, flexWrap: 'wrap' },
  mathRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: space.md },
  rule: { height: StyleSheet.hairlineWidth, marginVertical: 2 },
  partHead: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  track: { height: 6, borderRadius: 3, overflow: 'hidden' },
  fill: { height: 6, borderRadius: 3 },
  flag: { flexDirection: 'row', gap: space.sm, alignItems: 'flex-start' },
  bar: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    flexDirection: 'row',
    gap: space.md,
    paddingHorizontal: space.lg,
    paddingTop: space.md,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  save: {
    width: 52,
    height: 52,
    borderRadius: radius.lg,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
  },
});
