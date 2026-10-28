import { Ionicons } from '@expo/vector-icons';
import { BlurView } from 'expo-blur';
import * as Haptics from 'expo-haptics';
import { LinearGradient } from 'expo-linear-gradient';
import * as WebBrowser from 'expo-web-browser';
import { useEffect, useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import type { PurchasesPackage } from 'react-native-purchases';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, Skeleton, T } from '@/components/ui';
import { config } from '@/lib/config';
import { CATEGORY_ICON, CATEGORY_LABEL } from '@/lib/format';
import { buy, getPackages, purchasesAvailable, restore } from '@/lib/purchases';
import { useTeaser } from '@/lib/queries';
import { useSession } from '@/lib/session';
import { radius, space, usePalette } from '@/lib/theme';
import type { Category } from '@/lib/types';

const UNIT: Record<string, [string, string]> = {
  DAY: ['jour', 'jours'],
  WEEK: ['semaine', 'semaines'],
  MONTH: ['mois', 'mois'],
  YEAR: ['an', 'ans'],
};

function trialLabel(pkg: PurchasesPackage): string | null {
  const intro = pkg.product.introPrice;
  if (!intro || intro.price > 0) return null;
  const [one, many] = UNIT[intro.periodUnit] ?? ['', ''];
  return `${intro.periodNumberOfUnits} ${intro.periodNumberOfUnits > 1 ? many : one} gratuit${intro.periodNumberOfUnits > 1 ? 's' : ''}`;
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

export default function Paywall() {
  const p = usePalette();
  const { me, syncEntitlement } = useSession();
  const teaser = useTeaser();
  const [pkgs, setPkgs] = useState<PurchasesPackage[] | null>(null);
  const [selected, setSelected] = useState(0);
  const [busy, setBusy] = useState<'buy' | 'restore' | null>(null);

  useEffect(() => {
    getPackages()
      .then(setPkgs)
      .catch(() => setPkgs([]));
  }, []);

  const monthly = pkgs?.find((x) => x.packageType === 'MONTHLY');

  // The store confirms instantly; our server learns it from RevenueCat a moment
  // later. Poll briefly so the unlock feels immediate.
  async function unlock() {
    for (let i = 0; i < 8; i++) {
      const next = await syncEntitlement();
      if (next.entitlement.active) {
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        return true;
      }
      await wait(1500);
    }
    return false;
  }

  async function onBuy() {
    const pkg = pkgs?.[selected];
    if (!pkg) return;
    setBusy('buy');
    try {
      if (await buy(pkg)) {
        if (!(await unlock())) {
          Alert.alert('Paiement reçu', "L'activation prend quelques secondes de plus. Rouvre l'app dans un instant.");
        }
      }
    } catch (e: any) {
      Alert.alert('Achat impossible', e?.message ?? 'Réessaie dans un instant.');
    } finally {
      setBusy(null);
    }
  }

  async function onRestore() {
    setBusy('restore');
    try {
      await restore();
      if (!(await unlock())) Alert.alert('Aucun abonnement trouvé', 'Aucun achat actif sur ce compte store.');
    } catch (e: any) {
      Alert.alert('Restauration impossible', e?.message ?? 'Réessaie dans un instant.');
    } finally {
      setBusy(null);
    }
  }

  const t = teaser.data;
  const label = me?.prefs.home_label;
  const place = label && label !== 'Ma position' ? label : 'chez toi';
  const cats = Object.entries(t?.by_category ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3) as [Category, number][];

  return (
    <View style={{ flex: 1, backgroundColor: p.bg }}>
      <LinearGradient colors={[p.profitSoft, 'transparent']} style={StyleSheet.absoluteFill} end={{ x: 0.5, y: 0.5 }} />
      <SafeAreaView style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={s.wrap}>
          <T v="tiny" color="profit" style={{ textTransform: 'uppercase' }}>
            TechFlip Pro
          </T>
          {teaser.isLoading ? (
            <Skeleton h={80} style={{ marginTop: space.md }} />
          ) : t && t.count > 0 ? (
            <T v="title" style={{ marginTop: space.sm }}>
              {t.count} affaire{t.count > 1 ? 's' : ''} rentable{t.count > 1 ? 's' : ''} autour de {place} cette semaine
              {t.best_net ? (
                <T v="title" color="profit">
                  {`, jusqu'à +${t.best_net} €`}
                </T>
              ) : null}
            </T>
          ) : (
            <T v="title" style={{ marginTop: space.sm }}>
              Le scanner tourne pour toi en continu, autour de {place}.
            </T>
          )}

          {/* Preview: real categories, nothing you could act on */}
          <View style={s.preview}>
            {(cats.length ? cats : ([['console', 0], ['gpu', 0], ['pc', 0]] as [Category, number][])).map(([c, n]) => (
              <View key={c} style={[s.fake, { backgroundColor: p.surface, borderColor: p.border }]}>
                <View style={[s.fakeThumb, { backgroundColor: p.elevated }]}>
                  <Ionicons name={CATEGORY_ICON[c] as any} size={26} color={p.textMuted} />
                </View>
                <View style={{ flex: 1, gap: 6 }}>
                  <T style={{ fontWeight: '800', fontSize: 18 }} color="profit">
                    +•• €
                  </T>
                  <T v="small" color="muted">
                    {CATEGORY_LABEL[c]}
                    {n ? ` · ${n} cette semaine` : ''}
                  </T>
                </View>
              </View>
            ))}
            <BlurView intensity={28} tint="dark" style={[StyleSheet.absoluteFill, s.blur]}>
              <View style={[s.lock, { backgroundColor: p.overlay }]}>
                <Ionicons name="lock-closed" size={18} color="#fff" />
              </View>
            </BlurView>
          </View>

          <View style={{ gap: space.md, marginTop: space.lg }}>
            {[
              ['flash', 'Alertes instantanées sur les affaires pour toi'],
              ['map', 'Carte des bonnes affaires autour de toi'],
              ['layers', 'Valeur détaillée pièce par pièce'],
              ['shield-checkmark', 'Vérification photo et vendeur anti-arnaque'],
            ].map(([icon, label]) => (
              <View key={label} style={s.benefit}>
                <Ionicons name={icon as any} size={18} color={p.profit} />
                <T>{label}</T>
              </View>
            ))}
          </View>

          <View style={{ gap: space.sm, marginTop: space.xl }}>
            {pkgs === null ? (
              <>
                <Skeleton h={68} />
                <Skeleton h={68} />
              </>
            ) : pkgs.length === 0 ? (
              <T v="small" color="muted">
                {purchasesAvailable() ? 'Offres indisponibles pour le moment.' : 'Achats non configurés dans cette version de développement.'}
              </T>
            ) : (
              pkgs.map((pkg, i) => {
                const on = i === selected;
                const annual = pkg.packageType === 'ANNUAL';
                const saving =
                  annual && monthly ? Math.round((1 - pkg.product.price / (monthly.product.price * 12)) * 100) : 0;
                const trial = trialLabel(pkg);
                return (
                  <Pressable
                    key={pkg.identifier}
                    accessibilityRole="radio"
                    accessibilityState={{ selected: on }}
                    onPress={() => {
                      Haptics.selectionAsync();
                      setSelected(i);
                    }}
                    style={[
                      s.plan,
                      { backgroundColor: p.surface, borderColor: on ? p.profit : p.border, borderWidth: on ? 2 : StyleSheet.hairlineWidth },
                    ]}>
                    <View style={[s.radio, { borderColor: on ? p.profit : p.textFaint }]}>
                      {on ? <View style={[s.radioDot, { backgroundColor: p.profit }]} /> : null}
                    </View>
                    <View style={{ flex: 1 }}>
                      <T style={{ fontWeight: '700' }}>{annual ? 'Annuel' : pkg.packageType === 'MONTHLY' ? 'Mensuel' : pkg.product.title}</T>
                      <T v="small" color="muted">
                        {trial ? `${trial}, puis ` : ''}
                        {pkg.product.priceString}
                        {annual ? ' / an' : pkg.packageType === 'MONTHLY' ? ' / mois' : ''}
                        {annual && pkg.product.pricePerMonthString ? ` · ${pkg.product.pricePerMonthString}/mois` : ''}
                      </T>
                    </View>
                    {saving > 0 ? (
                      <View style={[s.badge, { backgroundColor: p.profit }]}>
                        <T v="tiny" color="onAccent">
                          -{saving}%
                        </T>
                      </View>
                    ) : null}
                  </Pressable>
                );
              })
            )}
          </View>

          <Button
            label={pkgs?.[selected] && trialLabel(pkgs[selected]) ? "Commencer l'essai gratuit" : 'Débloquer TechFlip Pro'}
            onPress={onBuy}
            loading={busy === 'buy'}
            disabled={!pkgs?.length || busy !== null}
            style={{ marginTop: space.lg }}
          />
          <T v="tiny" color="faint" style={{ textAlign: 'center', marginTop: space.sm }}>
            Sans engagement. Annulable à tout moment depuis ton compte store.
          </T>

          <View style={s.footer}>
            <Pressable onPress={onRestore} disabled={busy !== null} hitSlop={8}>
              <T v="small" color="muted">
                {busy === 'restore' ? 'Restauration…' : 'Restaurer mes achats'}
              </T>
            </Pressable>
            <T v="small" color="faint">·</T>
            <Pressable onPress={() => WebBrowser.openBrowserAsync(config.termsUrl)} hitSlop={8}>
              <T v="small" color="muted">CGU</T>
            </Pressable>
            <T v="small" color="faint">·</T>
            <Pressable onPress={() => WebBrowser.openBrowserAsync(config.privacyUrl)} hitSlop={8}>
              <T v="small" color="muted">Confidentialité</T>
            </Pressable>
          </View>
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { padding: space.xl, paddingBottom: space.xxl },
  preview: { marginTop: space.xl, gap: space.sm, borderRadius: radius.lg, overflow: 'hidden' },
  fake: {
    flexDirection: 'row',
    gap: space.md,
    padding: space.md,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: 'center',
  },
  fakeThumb: { width: 56, height: 56, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center' },
  blur: { alignItems: 'center', justifyContent: 'center' },
  lock: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center' },
  benefit: { flexDirection: 'row', gap: space.md, alignItems: 'center' },
  plan: { flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.lg, borderRadius: radius.lg },
  radio: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, alignItems: 'center', justifyContent: 'center' },
  radioDot: { width: 10, height: 10, borderRadius: 5 },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: radius.pill },
  footer: { flexDirection: 'row', justifyContent: 'center', gap: space.sm, marginTop: space.xl },
});
