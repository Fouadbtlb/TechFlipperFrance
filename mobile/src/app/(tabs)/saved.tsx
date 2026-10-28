import { FlatList, RefreshControl, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DealCard } from '@/components/DealCard';
import { EmptyState, Rule, Skeleton, T } from '@/components/ui';
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
        ItemSeparatorComponent={Rule}
        ListHeaderComponent={
          <T v="title" style={{ marginBottom: space.sm }}>
            Favoris
          </T>
        }
        contentContainerStyle={s.list}
        refreshControl={<RefreshControl refreshing={q.isRefetching} onRefresh={() => void q.refetch()} tintColor={p.textMuted} />}
        ListEmptyComponent={
          q.isLoading ? (
            <View style={{ gap: space.lg, paddingTop: space.lg }}>
              <Skeleton h={76} />
              <Skeleton h={76} />
            </View>
          ) : (
            <EmptyState
              title="Aucun favori"
              body="Garde ici les affaires à suivre pendant que tu contactes les vendeurs, avec le cœur en bas de chaque fiche."
            />
          )
        }
      />
    </SafeAreaView>
  );
}

const s = StyleSheet.create({ list: { padding: space.xl, paddingBottom: space.xxl, flexGrow: 1 } });
