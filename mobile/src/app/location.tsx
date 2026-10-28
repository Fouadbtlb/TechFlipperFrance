import { router } from 'expo-router';
import { StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { LocationPicker } from '@/components/LocationPicker';
import { Button, T } from '@/components/ui';
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
          <Button label="Fermer" kind="ghost" onPress={() => router.back()} style={s.close} />
        </View>
        <T color="muted">
          {`Actuellement : ${me?.prefs.home_label ?? 'non renseigné'}`}
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
  close: { height: 36, paddingHorizontal: 0 },
});
