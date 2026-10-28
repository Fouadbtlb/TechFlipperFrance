import { FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DealCard } from '@/components/DealCard';
import { EmptyState, Skeleton, T } from '@/components/ui';
import { useSaved } from '@/lib/queries';
import { space, usePalette } from '@/lib/theme';

export default function Saved() {
  const p = usePalette();
  const q = useSaved();
  const items = q.data?.items ?? [];
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: p.bg }} edges={['top']}>
      <FlatList
        data={items}
        keyExtractor={(d) => d.uid}
        renderItem={({ item }) => <DealCard deal={item} />}
        ItemSeparatorComponent={() => <View style={{ height: space.sm }} />}
        ListHeaderComponent={<T v="title" style={{ marginBottom: space.lg }}>Favoris</T>}
        contentContainerStyle={s.list}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => void q.refetch()} tintColor={p.textMuted} />}
        ListEmptyComponent={
          q.isLoading ? (
            <View style={{ gap: space.sm }}>
              <Skeleton h={120} />
              <Skeleton h={120} />
            </View>
          ) : (
            <EmptyState
              icon="heart-outline"
              title="Aucun favori"
              body="Touche le cœur sur une affaire pour la garder sous la main pendant que tu contactes le vendeur."
            />
          )
        }
      />
    </SafeAreaView>
  );
}

const s = StyleSheet.create({ list: { padding: space.lg, paddingBottom: space.xxl, flexGrow: 1 } });
