import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { useMemo, useState } from 'react';
import { FlatList, Pressable, RefreshControl, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DealCard } from '@/components/DealCard';
import { PushPrimer } from '@/components/PushPrimer';
import { Button, Chip, EmptyState, Segmented, Skeleton, T } from '@/components/ui';
import { CATEGORY_ICON, CATEGORY_LABEL, signedEuros } from '@/lib/format';
import { useFeed, type Sort } from '@/lib/queries';
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
  const q = useFeed(sort, cat);

  const items = useMemo(() => q.data?.pages.flatMap((pg) => pg.items) ?? [], [q.data]);
  const total = q.data?.pages[0]?.total ?? 0;
  const best = items.reduce((m, d) => Math.max(m, d.net), 0);

  const header = (
    <View style={{ gap: space.lg, paddingBottom: space.md }}>
      <View style={s.titleRow}>
        <View style={{ flex: 1 }}>
          <Pressable onPress={() => router.push('/location')} style={s.place} hitSlop={8}>
            <Ionicons name="navigate" size={13} color={p.textMuted} />
            <T v="small" color="muted">
              {me?.prefs.home_label ?? 'Ma position'}
            </T>
            <Ionicons name="chevron-down" size={13} color={p.textMuted} />
          </Pressable>
          <T v="title">Affaires</T>
        </View>
        {total > 0 ? (
          <View style={{ alignItems: 'flex-end' }}>
            <T v="h2" color="profit" style={{ fontVariant: ['tabular-nums'] }}>
              {signedEuros(best)}
            </T>
            <T v="tiny" color="muted">
              {total} affaire{total > 1 ? 's' : ''}
            </T>
          </View>
        ) : null}
      </View>
      {me?.prefs.notify && total > 0 ? <PushPrimer /> : null}
      <Segmented options={SORTS} value={sort} onChange={setSort} />
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.chips}>
        <Chip label="Tout" active={cat === null} onPress={() => setCat(null)} />
        {CATS.map((c) => (
          <Chip
            key={c}
            label={CATEGORY_LABEL[c]}
            icon={CATEGORY_ICON[c] as any}
            active={cat === c}
            onPress={() => setCat(cat === c ? null : c)}
          />
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
        ItemSeparatorComponent={() => <View style={{ height: space.sm }} />}
        ListHeaderComponent={header}
        contentContainerStyle={s.list}
        onEndReachedThreshold={0.6}
        onEndReached={() => q.hasNextPage && !q.isFetchingNextPage && q.fetchNextPage()}
        refreshControl={
          <RefreshControl refreshing={q.isRefetching && !q.isFetchingNextPage} onRefresh={() => void q.refetch()} tintColor={p.textMuted} />
        }
        ListEmptyComponent={
          q.isLoading ? (
            <View style={{ gap: space.sm }}>
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} h={120} />
              ))}
            </View>
          ) : q.isError ? (
            <EmptyState
              icon="cloud-offline-outline"
              title="Chargement impossible"
              body="Vérifie ta connexion."
              action={<Button label="Réessayer" kind="secondary" onPress={() => q.refetch()} />}
            />
          ) : (
            <EmptyState
              icon="sparkles-outline"
              title="Rien pour l’instant"
              body={
                cat
                  ? 'Aucune affaire dans cette catégorie pour l’instant. Le scanner tourne : on te prévient dès qu’il en trouve une.'
                  : 'Le scanner tourne en continu. Élargis ton rayon ou baisse ton bénéfice minimum dans les réglages.'
              }
              action={<Button label="Ajuster mes critères" kind="secondary" onPress={() => router.push('/settings')} />}
            />
          )
        }
      />
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  list: { padding: space.lg, paddingBottom: space.xxl, flexGrow: 1 },
  titleRow: { flexDirection: 'row', alignItems: 'flex-end' },
  place: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: 2 },
  chips: { gap: space.sm, paddingRight: space.lg },
});
