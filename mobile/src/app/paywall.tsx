import * as Haptics from 'expo-haptics';
import * as WebBrowser from 'expo-web-browser';
import { useEffect, useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import type { PurchasesPackage } from 'react-native-purchases';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Button, LedgerRow, Rule, Skeleton, T } from '@/components/ui';
import { config } from '@/lib/config';
import { reminderDate, scheduleTrialReminder, trialEnd } from '@/lib/engagement';
import { CATEGORY_LABEL } from '@/lib/format';
import { buy, getPackages, purchasesAvailable, restore } from '@/lib/purchases';
import { useTeaser } from '@/lib/queries';
import { useSession } from '@/lib/session';
import { radius, space, usePalette } from '@/lib/theme';
import type { Category } from '@/lib/types';

// [singular, plural, feminine?] so the adjective agrees: "1 semaine gratuite", "3 jours gratuits".
const UNIT: Record<string, [string, string, boolean]> = {
  DAY: ['jour', 'jours', false],
  WEEK: ['semaine', 'semaines', true],
  MONTH: ['mois', 'mois', false],
  YEAR: ['an', 'ans', false],
};

function trialLabel(pkg: PurchasesPackage): string | null {
  const intro = pkg.product.introPrice;
  if (!intro || intro.price > 0) return null;
  const [one, many, fem] = UNIT[intro.periodUnit] ?? ['', '', false];
  const n = intro.periodNumberOfUnits;
  return `${n} ${n > 1 ? many : one} gratuit${fem ? 'e' : ''}${n > 1 ? 's' : ''}`;
}

const BENEFITS = [
  'Les affaires rentables pour toi, au moment où elles paraissent',
  'La carte des affaires autour de chez toi',
  'La valeur de chaque pièce, au prix du marché',
  'Photos et vendeur vérifiés avant de te déplacer',
];

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
  const current = pkgs?.[selected];

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
    if (!current) return;
    setBusy('buy');
    try {
      if (await buy(current)) {
        const intro = current.product.introPrice;
        if (intro && intro.price === 0) {
          // keep the promise made on the timeline
          scheduleTrialReminder(trialEnd(intro.periodUnit, intro.periodNumberOfUnits), current.product.priceString).catch(
            () => undefined,
          );
        }
        if (!(await unlock())) {
          Alert.alert('Paiement reçu', 'L’activation prend quelques secondes de plus. Rouvre l’application dans un instant.');
        }
      }
    } catch {
      Alert.alert('Achat impossible', 'Le paiement n’a pas abouti. Aucun montant n’a été débité. Réessaie dans un instant.');
    } finally {
      setBusy(null);
    }
  }

  async function onRestore() {
    setBusy('restore');
    try {
      await restore();
      if (!(await unlock())) Alert.alert('Aucun abonnement trouvé', 'Aucun abonnement actif sur ce compte App Store ou Google Play.');
    } catch {
      Alert.alert('Restauration impossible', 'Vérifie ta connexion et réessaie.');
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
    <SafeAreaView style={{ flex: 1, backgroundColor: p.bg }}>
      <ScrollView contentContainerStyle={s.wrap}>
        <T v="label" color="brass">
          Abonnement
        </T>
        <T v="title" style={{ marginTop: space.sm }}>
          Les bonnes affaires, avant les autres.
        </T>

        {/* Real figures for this week, nothing you could act on */}
        <View style={[s.ledger, { borderColor: p.border }]}>
          <T v="label" color="muted" style={{ marginBottom: space.sm }}>
            {`Cette semaine autour de ${place}`}
          </T>
          {teaser.isLoading ? (
            <Skeleton h={90} />
          ) : t && t.count > 0 ? (
            <>
              <LedgerRow label="Affaires rentables" value={String(t.count)} />
              {t.best_net ? <LedgerRow label="La meilleure" value={`+${t.best_net} €`} tone="profit" /> : null}
              {cats.map(([c, n]) => (
                <LedgerRow key={c} label={CATEGORY_LABEL[c] ?? c} value={String(n)} tone="muted" />
              ))}
            </>
          ) : (
            <T color="muted">Le relevé de la semaine est en cours. Le service tourne en continu autour de {place}.</T>
          )}
        </View>

        <View style={{ marginTop: space.xl }}>
          {BENEFITS.map((b, i) => (
            <View key={b}>
              {i > 0 ? <Rule /> : null}
              <T style={{ paddingVertical: space.md }}>{b}</T>
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
                  style={[s.plan, { borderColor: on ? p.accent : p.border, borderWidth: on ? 1.5 : StyleSheet.hairlineWidth }]}>
                  <View style={[s.radio, { borderColor: on ? p.accent : p.textFaint }]}>
                    {on ? <View style={[s.radioDot, { backgroundColor: p.accent }]} /> : null}
                  </View>
                  <View style={{ flex: 1 }}>
                    <T v="strong">{annual ? 'Annuel' : pkg.packageType === 'MONTHLY' ? 'Mensuel' : pkg.product.title}</T>
                    <T v="small" color="muted">
                      {trial ? `${trial}, puis ` : ''}
                      {pkg.product.priceString}
                      {annual ? ' par an' : pkg.packageType === 'MONTHLY' ? ' par mois' : ''}
                      {annual && pkg.product.pricePerMonthString ? `, soit ${pkg.product.pricePerMonthString} par mois` : ''}
                    </T>
                  </View>
                  {saving > 0 ? (
                    <T v="label" color="brass">
                      {`−${saving} %`}
                    </T>
                  ) : null}
                </Pressable>
              );
            })
          )}
        </View>

        {current && trialLabel(current) ? <TrialTimeline pkg={current} /> : null}

        <Button
          label={current && trialLabel(current) ? 'Commencer l’essai gratuit' : 'S’abonner'}
          onPress={onBuy}
          loading={busy === 'buy'}
          disabled={!pkgs?.length || busy !== null}
          style={{ marginTop: space.xl }}
        />
        <T v="small" color="faint" style={{ textAlign: 'center', marginTop: space.md }}>
          Sans engagement. Résiliable à tout moment depuis ton compte App Store ou Google Play.
        </T>

        <View style={s.footer}>
          <Button label={busy === 'restore' ? 'Restauration…' : 'Restaurer mes achats'} kind="ghost" onPress={onRestore} style={s.link} />
          <Button label="Conditions" kind="ghost" onPress={() => WebBrowser.openBrowserAsync(config.termsUrl)} style={s.link} />
          <Button label="Confidentialité" kind="ghost" onPress={() => WebBrowser.openBrowserAsync(config.privacyUrl)} style={s.link} />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const fmtDay = (d: Date) => d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' });

/** No surprise charge: the exact dates, stated before the user commits. */
function TrialTimeline({ pkg }: { pkg: PurchasesPackage }) {
  const p = usePalette();
  const intro = pkg.product.introPrice!;
  const now = new Date();
  const end = trialEnd(intro.periodUnit, intro.periodNumberOfUnits, now);
  const steps = [
    { title: 'Aujourd’hui', body: 'Accès complet, sans payer.' },
    { title: fmtDay(reminderDate(end, now)), body: 'Un rappel t’indique que l’essai se termine.' },
    { title: fmtDay(end), body: `Premier paiement de ${pkg.product.priceString}, sauf résiliation avant cette date.` },
  ];
  return (
    <View style={[s.timeline, { borderColor: p.border }]}>
      {steps.map((st, i) => (
        <View key={st.title} style={s.step}>
          <View style={{ alignItems: 'center', width: 12 }}>
            <View style={[s.stepDot, { backgroundColor: i === 0 ? p.accent : 'transparent', borderColor: p.accent }]} />
            {i < steps.length - 1 ? <View style={[s.stepLine, { backgroundColor: p.border }]} /> : null}
          </View>
          <View style={{ flex: 1, paddingBottom: i < steps.length - 1 ? space.lg : 0 }}>
            <T v="strong">{st.title}</T>
            <T v="small" color="muted">
              {st.body}
            </T>
          </View>
        </View>
      ))}
    </View>
  );
}

const s = StyleSheet.create({
  wrap: { padding: space.xl, paddingBottom: space.xxl },
  ledger: { marginTop: space.xl, paddingTop: space.lg, borderTopWidth: StyleSheet.hairlineWidth, borderBottomWidth: StyleSheet.hairlineWidth, paddingBottom: space.md },
  plan: { flexDirection: 'row', alignItems: 'center', gap: space.md, padding: space.lg, borderRadius: radius.md },
  radio: { width: 20, height: 20, borderRadius: 10, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
  radioDot: { width: 10, height: 10, borderRadius: 5 },
  timeline: { marginTop: space.xl, padding: space.lg, borderRadius: radius.md, borderWidth: StyleSheet.hairlineWidth },
  step: { flexDirection: 'row', gap: space.md },
  stepDot: { width: 10, height: 10, borderRadius: 5, borderWidth: 1.5, marginTop: 6 },
  stepLine: { width: StyleSheet.hairlineWidth, flex: 1, marginTop: 4 },
  footer: { flexDirection: 'row', justifyContent: 'center', flexWrap: 'wrap', marginTop: space.lg },
  link: { height: 40, paddingHorizontal: space.sm },
});
