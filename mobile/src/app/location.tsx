import { Ionicons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { LocationPicker } from '@/components/LocationPicker';
import { T } from '@/components/ui';
import { useInvalidateDeals } from '@/lib/queries';
import { useSession } from '@/lib/session';
import { space, usePalette } from '@/lib/theme';

export default function ChangeLocation() {
  const p = usePalette();
  const { me, updatePrefs } = useSession();
  const invalidate = useInvalidateDeals();
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: p.bg }} edges={['bottom']}>
      <View style={s.wrap}>
        <View style={s.head}>
          <T v="h2">Point de départ</T>
          <Pressable accessibilityLabel="Fermer" onPress={() => router.back()} hitSlop={12}>
            <Ionicons name="close" size={24} color={p.textMuted} />
          </Pressable>
        </View>
        <T color="muted">
          Actuellement : <T style={{ fontWeight: '700' }}>{me?.prefs.home_label ?? '—'}</T>
        </T>
        <LocationPicker
          onPick={async (pl) => {
            await updatePrefs(pl);
            invalidate();
            router.back();
          }}
        />
      </View>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  wrap: { padding: space.xl, gap: space.lg },
  head: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
});
