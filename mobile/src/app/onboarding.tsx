import { ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { LocationPicker } from '@/components/LocationPicker';
import { Rule, T } from '@/components/ui';
import { useSession } from '@/lib/session';
import { space, usePalette } from '@/lib/theme';

const POINTS = [
  {
    n: 'I',
    title: 'Seulement ce qui rapporte',
    body: 'Leboncoin et 2ememain sont lus en continu. Tu ne vois que les annonces qui laissent une marge.',
  },
  {
    n: 'II',
    title: 'Estimé pièce par pièce',
    body: 'Un PC vendu 250 € avec une carte graphique dedans ? Chaque composant est chiffré au prix réel du marché.',
  },
  {
    n: 'III',
    title: 'Calculé depuis chez toi',
    body: 'Trajet ou envoi déduits : le bénéfice affiché est ce qui te reste vraiment.',
  },
];

export default function Onboarding() {
  const p = usePalette();
  const { updatePrefs } = useSession();
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: p.bg }}>
      <ScrollView contentContainerStyle={s.wrap} keyboardShouldPersistTaps="handled">
        <T v="h2" style={{ letterSpacing: 0.5 }}>
          TechFlip
        </T>
        <T v="label" color="brass" style={{ marginTop: 2 }}>
          Achat · Revente · Occasion
        </T>
        <Rule style={{ marginVertical: space.xl }} />

        <T v="title">L’occasion, estimée à sa juste valeur.</T>

        <View style={{ gap: space.xl, marginTop: space.xxl }}>
          {POINTS.map((pt) => (
            <View key={pt.n} style={s.point}>
              <T v="h2" color="brass" style={s.numeral}>
                {pt.n}
              </T>
              <View style={{ flex: 1, gap: 2 }}>
                <T v="strong">{pt.title}</T>
                <T color="muted">{pt.body}</T>
              </View>
            </View>
          ))}
        </View>

        <View style={{ flex: 1, minHeight: space.xxl }} />
        <T v="label" color="muted" style={{ marginBottom: space.md }}>
          Ton point de départ
        </T>
        <LocationPicker
          cta="Utiliser ma position"
          onPick={async (pl) => {
            await updatePrefs(pl);
          }}
        />
        <T v="small" color="faint" style={{ marginTop: space.md, textAlign: 'center' }}>
          Position arrondie à environ 1{' '}km. Elle ne sert qu’à calculer les distances.
        </T>
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  wrap: { flexGrow: 1, padding: space.xl, paddingTop: space.xl },
  point: { flexDirection: 'row', gap: space.lg, alignItems: 'flex-start' },
  numeral: { width: 30, textAlign: 'right', lineHeight: 24 },
});
