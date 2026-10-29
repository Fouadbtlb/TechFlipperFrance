// Web stand-in for the map tab. react-native-maps has no web implementation,
// and importing it crashes the whole web bundle, so the browser preview lists
// the same pins as cards. The phone apps keep the real map in map.tsx.
import { FlatList, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DealCard } from '@/components/DealCard';
import { EmptyState, T } from '@/components/ui';
import { usePins } from '@/lib/queries';
import { space } from '@/lib/theme';

export default function MapScreen() {
  const q = usePins();
  const pins = q.data?.items ?? [];

  return (
    <SafeAreaView edges={['top']} style={s.root}>
      <View style={s.head}>
        <T v="label">{q.isLoading ? '…' : `${pins.length} affaire${pins.length > 1 ? 's' : ''}`}</T>
        <T v="body" color="muted">La carte s’affiche sur l’app iPhone et Android.</T>
      </View>
      {!q.isLoading && pins.length === 0 ? (
        <EmptyState title="Aucune affaire sur la carte" body="Élargis ton rayon dans les réglages." />
      ) : (
        <FlatList
          data={pins}
          keyExtractor={(item) => item.uid}
          contentContainerStyle={s.list}
          renderItem={({ item }) => <DealCard deal={item.card} compact />}
        />
      )}
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1 },
  head: { paddingHorizontal: space.md, paddingVertical: space.sm, gap: 4 },
  list: { padding: space.md, gap: space.sm },
});
