import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { FlatList, Pressable, RefreshControl, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DealCard } from '@/components/DealCard';
import { PushPrimer } from '@/components/PushPrimer';
import { Button, Chip, EmptyState, Rule, Skeleton, T, Tabs } from '@/components/ui';
import { CATEGORY_LABEL, signedEuros } from '@/lib/format';
import { useFeed, type Bucket, type Sort } from '@/lib/queries';
import { useSession } from '@/lib/session';
import { space, usePalette } from '@/lib/theme';
import type { Category } from '@/lib/types';

const SORTS: { key: Sort; label: string }[] = [
  { key: 'profit', label: 'Rentables' },
  { key: 'distance', label: 'Proches' },
  { key: 'recent', label: 'Récentes' },
];

const CATS: Category[] = ['console', 'pc', 'gpu', 'laptop', 'phone', 'cpu', 'monitor', 'parts', 'accessory'];

export default function Feed() {
  const p = usePalette();
  const { me } = useSession();
  const [sort, setSort] = useState<Sort>('profit');
  const [cat, setCat] = useState<Category | null>(null);
  const [bucket, setBucket] = useState<Bucket>('reliable');
  const q = useFeed(sort, cat, bucket);
  const counts = q.data?.pages[0]?.counts;

  const items = useMemo(() => q.data?.pages.flatMap((pg) => pg.items) ?? [], [q.data]);
  const total = q.data?.pages[0]?.total ?? 0;
  const best = items.reduce((m, d) => Math.max(m, d.net), 0);

  const header = (
    <View style={{ gap: space.lg, paddingBottom: space.sm }}>
      <View style={s.titleRow}>
        <View style={{ flex: 1 }}>
          <Pressable onPress={() => router.push('/location')} hitSlop={8} accessibilityRole="button">
            <T v="label" color="brass">
              {`${me?.prefs.home_label ?? 'Ma position'}  ›`}
            </T>
          </Pressable>
          <T v="title" style={{ marginTop: 2 }}>
            Affaires
          </T>
        </View>
        {total > 0 ? (
          <View style={{ alignItems: 'flex-end' }}>
            <T v="money" color="profit" style={{ fontVariant: ['tabular-nums'] }}>
              {signedEuros(best)}
            </T>
            <T v="small" color="muted">
              {bucket === 'reliable' ? `la meilleure sur ${total}` : `${total} à vérifier`}
            </T>
          </View>
        ) : null}
      </View>
      {me?.prefs.notify && total > 0 ? <PushPrimer /> : null}
      <View style={s.buckets}>
        <BucketLink label="Fiables" n={counts?.reliable} active={bucket === 'reliable'} onPress={() => setBucket('reliable')} />
        <T v="small" color="faint">·</T>
        <BucketLink label="À vérifier" n={counts?.check} active={bucket === 'check'} onPress={() => setBucket('check')} />
      </View>
      {bucket === 'check' ? (
        <T v="small" color="muted">
          Estimation moins sûre ou point de vigilance : regarde bien les photos et pose des questions avant de te déplacer.
        </T>
      ) : null}
      <Tabs options={SORTS} value={sort} onChange={setSort} />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
        <Chip label="Tout" active={cat === null} onPress={() => setCat(null)} />
        {CATS.map((c) => (
          <Chip key={c} label={CATEGORY_LABEL[c]} active={cat === c} onPress={() => setCat(cat === c ? null : c)} />
        ))}
      </ScrollView>
    </View>
  );

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: p.bg }} edges={['top']}>
      <FlatList
        data={items}
        keyExtractor={(d) => d.uid}
        renderItem={({ item }) => <DealCard deal={item} />}
        ItemSeparatorComponent={Rule}
        ListHeaderComponent={header}
        contentContainerStyle={s.list}
        onEndReachedThreshold={0.6}
        onEndReached={() => q.hasNextPage && !q.isFetchingNextPage && q.fetchNextPage()}
        refreshControl={
          <RefreshControl refreshing={q.isRefetching && !q.isFetchingNextPage} onRefresh={() => void q.refetch()} tintColor={p.textMuted} />
        }
        ListEmptyComponent={
          q.isLoading ? (
            <View style={{ gap: space.lg, paddingTop: space.lg }}>
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} h={76} />
              ))}
            </View>
          ) : q.isError ? (
            <EmptyState
              title="Chargement impossible"
              body="Vérifie ta connexion."
              action={<Button label="Réessayer" kind="secondary" onPress={() => q.refetch()} />}
            />
          ) : (
            <EmptyState
              title="Rien pour l’instant"
              body={
                cat
                  ? 'Aucune affaire dans cette catégorie pour l’instant. Le service tourne : on te prévient dès qu’il en trouve une.'
                  : 'Le service tourne en continu. Élargis ton rayon ou baisse ton bénéfice minimum dans les réglages.'
              }
              action={<Button label="Ajuster mes critères" kind="secondary" onPress={() => router.push('/settings')} />}
            />
          )
        }
      />
    </SafeAreaView>
  );
}

function BucketLink({ label, n, active, onPress }: { label: string; n?: number; active: boolean; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="tab" accessibilityState={{ selected: active }} onPress={onPress} hitSlop={8}>
      <T v="strong" color={active ? 'text' : 'faint'} style={active ? { textDecorationLine: 'underline' } : undefined}>
        {n != null ? `${label} (${n})` : label}
      </T>
    </Pressable>
  );
}

const s = StyleSheet.create({
  buckets: { flexDirection: 'row', gap: space.sm, alignItems: 'center' },
  list: { padding: space.xl, paddingBottom: space.xxl, flexGrow: 1 },
  titleRow: { flexDirection: 'row', alignItems: 'flex-end' },
  chips: { gap: space.sm, paddingRight: space.lg },
});
