import { Ionicons } from '@expo/vector-icons';
import { Image } from 'expo-image';
import * as Haptics from 'expo-haptics';
import { router, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { ActionSheetIOS, Alert, FlatList, Platform, Pressable, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Button, EmptyState, LedgerRow, Rule, SectionTitle, Skeleton, T } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { noteListingOpened } from '@/lib/engagement';
import { ago, euros, km, signedEuros } from '@/lib/format';
import { useDeal, useHide, useToggleSave } from '@/lib/queries';
import { radius, space, usePalette } from '@/lib/theme';
import type { DealDetail, Part } from '@/lib/types';

const SOURCE_LABEL: Record<Part['source'], string> = {
  learned: 'prix du marché',
  blend: 'marché et estimation',
  seed: 'estimation',
  ai: 'estimation par l’IA',
  unknown: 'non chiffré',
};

const ZONE_LABEL = { EASY: 'à proximité', MEDIUM: 'à distance moyenne', HARD: 'éloignée' } as const;

export default function DealScreen() {
  const { uid } = useLocalSearchParams<{ uid: string }>();
  const p = usePalette();
  const insets = useSafeAreaInsets();
  const q = useDeal(uid);
  const save = useToggleSave(uid);
  const hide = useHide(uid);

  function more() {
    const run = (i: number) => {
      // optimistic: the line leaves the lists at once, the server catches up
      if (i === 0 || i === 1) {
        hide.mutate(i === 0 ? 'sold' : 'not_interested');
        router.back();
      }
    };
    const options = ['Déjà vendue', 'Ça ne m’intéresse pas', 'Annuler'];
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
        <View style={{ padding: space.xl, paddingTop: insets.top + 60, gap: space.md }}>
          <Skeleton h={280} />
          <Skeleton h={56} w="60%" />
          <Skeleton h={140} />
        </View>
      ) : q.isError || !d ? (
        <EmptyState
          title={q.error instanceof ApiError && q.error.status === 404 ? 'Annonce introuvable' : 'Chargement impossible'}
          body={q.error instanceof ApiError ? q.error.message : undefined}
          action={<Button label="Retour" kind="secondary" onPress={() => router.back()} />}
        />
      ) : (
        <Detail d={d} bottomPad={insets.bottom + 100} />
      )}

      <View style={[s.header, { top: insets.top + 6 }]} pointerEvents="box-none">
        <RoundButton icon="chevron-back" label="Retour" onPress={() => router.back()} />
        {d ? <RoundButton icon="ellipsis-horizontal" label="Plus d’options" onPress={more} /> : null}
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
            style={[s.save, { borderColor: p.border }]}>
            <Ionicons name={d.saved ? 'heart' : 'heart-outline'} size={21} color={d.saved ? p.risk : p.text} />
          </Pressable>
          <Button
            label={`Voir l’annonce sur ${d.source === '2ememain' ? '2ememain' : 'Leboncoin'}`}
            onPress={async () => {
              await WebBrowser.openBrowserAsync(d.url);
              noteListingOpened(d.uid).catch(() => undefined);
            }}
            style={{ flex: 1 }}
          />
        </View>
      ) : null}
    </View>
  );
}

function RoundButton({ icon, label, onPress }: { icon: 'chevron-back' | 'ellipsis-horizontal'; label: string; onPress: () => void }) {
  const p = usePalette();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      onPress={onPress}
      hitSlop={8}
      style={[s.round, { backgroundColor: p.overlay }]}>
      <Ionicons name={icon} size={20} color="#F6F1E6" />
    </Pressable>
  );
}

function Detail({ d, bottomPad }: { d: DealDetail; bottomPad: number }) {
  const p = usePalette();
  const { width } = useWindowDimensions();
  const [page, setPage] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const drop = d.prev_price ? d.prev_price - d.price : 0;
  const partsTotal = d.parts.reduce((sum, x) => sum + (x.value ?? 0), 0);
  const sellerFlags = d.seller?.flags ?? [];
  const where = d.mode === 'ship' ? 'Envoi' : `${km(d.distance_km)}, ${ZONE_LABEL[d.zone]}`;
  const confidence = Math.round((d.confidence ?? 0) * 100);

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: bottomPad }}>
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
              <Image source={{ uri: item }} style={{ width, height: width * 0.8, backgroundColor: p.rule }} contentFit="cover" transition={150} />
            )}
          />
        ) : (
          <View style={{ width, height: width * 0.55, backgroundColor: p.rule }} />
        )}
        {d.images.length > 1 ? (
          <View style={[s.counter, { backgroundColor: p.overlay }]}>
            <T v="label" style={{ color: '#F6F1E6' }}>{`${page + 1} / ${d.images.length}`}</T>
          </View>
        ) : null}
      </View>

      <View style={{ padding: space.xl }}>
        <T v="label" color="brass">
          {where}
        </T>
        <T v="h2" style={{ marginTop: space.sm, fontSize: 26, lineHeight: 31 }}>
          {d.title}
        </T>
        <T v="small" color="muted" style={{ marginTop: space.xs }}>
          {[d.city, d.department].filter(Boolean).join(', ') || 'Lieu non communiqué'} · {ago(d.first_seen)}
          {d.condition ? ` · ${d.condition}` : ''}
        </T>

        <Rule style={{ marginVertical: space.xl }} />

        <T v="label" color="muted">
          Ce qu’il te reste
        </T>
        <T v="hero" color="profit" style={{ fontVariant: ['tabular-nums'], marginTop: 2 }}>
          {signedEuros(d.net)}
        </T>
        {drop > 0 ? (
          <T v="small" color="profit">
            {`Prix baissé de ${euros(drop)}, il était à ${euros(d.prev_price)}.`}
          </T>
        ) : null}

        <SectionTitle>Le calcul</SectionTitle>
        <LedgerRow label="Revente estimée" value={euros(d.value)} />
        <LedgerRow label="Prix demandé" value={`− ${euros(d.price)}`} />
        <LedgerRow
          label={d.mode === 'ship' ? 'Frais d’envoi' : `Trajet aller-retour, ${km(d.distance_km)}`}
          value={`− ${euros(d.logistics)}`}
        />
        <Rule style={{ marginVertical: space.sm }} />
        <LedgerRow label="Bénéfice net" value={signedEuros(d.net)} strong />

        {d.parts.length ? (
          <>
            <SectionTitle>{d.parts.length > 1 ? 'Pièce par pièce' : 'Valeur de revente'}</SectionTitle>
            {d.parts.map((part, i) => (
              <View key={`${part.label}-${i}`} style={{ paddingVertical: 4 }}>
                <LedgerRow label={`${part.label}${part.qty > 1 ? ` ×${part.qty}` : ''}`} value={euros(part.value)} />
                <T v="small" color="faint" style={{ marginTop: -4 }}>
                  {SOURCE_LABEL[part.source]}
                  {part.source === 'learned' || part.source === 'blend' ? `, ${part.n} annonces comparées` : ''}
                  {part.condition !== 'working' ? ', état dégradé' : ''}
                </T>
              </View>
            ))}
            {partsTotal > d.value + 1 ? (
              <>
                <Rule style={{ marginVertical: space.sm }} />
                <LedgerRow label="Total au prix du marché" value={euros(partsTotal)} />
                <LedgerRow label="Décote pour revente rapide" value={`− ${euros(partsTotal - d.value)}`} />
                <T v="small" color="faint">
                  Ce qu’on cède pour vendre vite : une console se revend presque au prix, une alimentation se brade.
                </T>
              </>
            ) : null}
          </>
        ) : null}

        <SectionTitle>Confiance</SectionTitle>
        <LedgerRow
          label="Fiabilité du prix"
          value={`${confidence} %`}
          tone={confidence >= 60 ? 'profit' : confidence >= 30 ? 'warn' : 'risk'}
        />
        <LedgerRow label="Photos vérifiées par l’IA" value={d.photo_checked ? 'Oui' : 'Non'} tone={d.photo_checked ? 'profit' : 'muted'} />
        {d.scam_score != null ? (
          <LedgerRow
            label="Risque d’arnaque"
            value={`${Math.round(d.scam_score)} sur 10`}
            tone={d.scam_score >= 6 ? 'risk' : d.scam_score >= 3 ? 'warn' : 'profit'}
          />
        ) : null}
        {d.seller?.known ? (
          <LedgerRow
            label={`Vendeur ${d.seller.kind ?? ''}`.trim()}
            value={
              [
                d.seller.age_days != null
                  ? d.seller.age_days >= 365
                    ? `${Math.floor(d.seller.age_days / 365)} an${d.seller.age_days >= 730 ? 's' : ''}`
                    : `${d.seller.age_days} j`
                  : null,
                d.seller.rating != null && d.seller.reviews ? `${d.seller.rating.toFixed(1)}/5, ${d.seller.reviews} avis` : null,
              ]
                .filter(Boolean)
                .join(' · ') || 'n.c.'
            }
            tone="muted"
          />
        ) : null}
        {sellerFlags.map((f) => (
          <View key={f.text} style={[s.note, { borderLeftColor: f.level === 'risk' ? p.risk : p.warn }]}>
            <T v="small" color={f.level === 'risk' ? 'risk' : 'warn'}>
              {f.text}
            </T>
          </View>
        ))}
        {!d.shippable && d.mode === 'pickup' ? (
          <View style={[s.note, { borderLeftColor: p.border }]}>
            <T v="small" color="muted">
              Remise en main propre uniquement : vérifie et teste sur place.
            </T>
          </View>
        ) : null}

        {d.description ? (
          <>
            <SectionTitle>Description du vendeur</SectionTitle>
            <Pressable onPress={() => setExpanded((x) => !x)}>
              <T color="muted" numberOfLines={expanded ? undefined : 5}>
                {d.description}
              </T>
              <T v="label" style={{ marginTop: space.sm }}>
                {expanded ? 'Réduire' : 'Lire la suite'}
              </T>
            </Pressable>
          </>
        ) : null}
      </View>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  header: { position: 'absolute', left: space.lg, right: space.lg, flexDirection: 'row', justifyContent: 'space-between' },
  round: { width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center' },
  counter: { position: 'absolute', bottom: 12, right: 12, paddingHorizontal: 8, paddingVertical: 4, borderRadius: radius.sm },
  note: { borderLeftWidth: 2, paddingLeft: space.md, paddingVertical: 2, marginTop: space.sm },
  bar: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    flexDirection: 'row',
    gap: space.md,
    paddingHorizontal: space.xl,
    paddingTop: space.md,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  save: { width: 52, height: 52, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center', borderWidth: 1 },
});
