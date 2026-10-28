import { Ionicons } from '@expo/vector-icons';
import { LinearGradient } from 'expo-linear-gradient';
import { ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { LocationPicker } from '@/components/LocationPicker';
import { T, type IconName } from '@/components/ui';
import { useSession } from '@/lib/session';
import { space, usePalette } from '@/lib/theme';

const POINTS: { icon: IconName; title: string; body: string }[] = [
  {
    icon: 'flash-outline',
    title: 'Les bonnes affaires, pas les annonces',
    body: 'On scanne Leboncoin et 2ememain en continu et on ne te montre que ce qui rapporte.',
  },
  {
    icon: 'layers-outline',
    title: 'Valorisé pièce par pièce',
    body: "Un PC à 250 € avec une RTX dedans ? On chiffre chaque composant au prix du marché réel.",
  },
  {
    icon: 'navigate-outline',
    title: 'Calculé depuis chez toi',
    body: "Trajet ou envoi déduits : le bénéfice affiché est ce qui te reste vraiment.",
  },
];

export default function Onboarding() {
  const p = usePalette();
  const { updatePrefs } = useSession();
  return (
    <View style={{ flex: 1, backgroundColor: p.bg }}>
      <LinearGradient colors={[p.profitSoft, 'transparent']} style={StyleSheet.absoluteFill} end={{ x: 0.5, y: 0.55 }} />
      <SafeAreaView style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={s.wrap} keyboardShouldPersistTaps="handled">
          <View style={[s.logo, { backgroundColor: p.profit }]}>
            <Ionicons name="trending-up" size={26} color={p.onAccent} />
          </View>
          <T v="title" style={{ fontSize: 34, lineHeight: 38 }}>
            Achète malin.{'\n'}
            <T v="title" color="profit" style={{ fontSize: 34 }}>
              Revends gagnant.
            </T>
          </T>

          <View style={{ gap: space.xl, marginTop: space.xl }}>
            {POINTS.map((pt) => (
              <View key={pt.title} style={s.point}>
                <View style={[s.pointIcon, { backgroundColor: p.surface, borderColor: p.border }]}>
                  <Ionicons name={pt.icon} size={20} color={p.profit} />
                </View>
                <View style={{ flex: 1, gap: 2 }}>
                  <T style={{ fontWeight: '700' }}>{pt.title}</T>
                  <T v="small" color="muted">
                    {pt.body}
                  </T>
                </View>
              </View>
            ))}
          </View>

          <View style={{ flex: 1, minHeight: space.xxl }} />
          <T v="small" color="muted" style={{ marginBottom: space.md }}>
            D’où pars-tu chercher tes affaires ?
          </T>
          <LocationPicker cta="Commencer avec ma position" onPick={async (pl) => { await updatePrefs(pl); }} />
          <T v="tiny" color="faint" style={{ marginTop: space.md, textAlign: 'center' }}>
            Position arrondie à ~1 km. Elle ne sert qu’à calculer les distances.
          </T>
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { flexGrow: 1, padding: space.xl, paddingTop: space.xxl },
  logo: { width: 52, height: 52, borderRadius: 16, alignItems: 'center', justifyContent: 'center', marginBottom: space.xl },
  point: { flexDirection: 'row', gap: space.md, alignItems: 'flex-start' },
  pointIcon: {
    width: 40,
    height: 40,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
  },
});
