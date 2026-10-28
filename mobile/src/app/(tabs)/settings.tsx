import * as Application from 'expo-application';
import { router } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Switch, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Chip, Rule, SectionTitle, T } from '@/components/ui';
import { api, signOut } from '@/lib/api';
import { config } from '@/lib/config';
import { CATEGORY_LABEL } from '@/lib/format';
import { enablePush } from '@/lib/notifications';
import { manageSubscription, restore } from '@/lib/purchases';
import { useInvalidateDeals } from '@/lib/queries';
import { useSession } from '@/lib/session';
import { space, usePalette } from '@/lib/theme';
import type { Category, Prefs } from '@/lib/types';

const RADII = [10, 30, 60, 100, 200];
const PROFITS = [20, 30, 50, 80, 120];
const CATS: Category[] = ['console', 'pc', 'gpu', 'laptop', 'phone', 'cpu', 'monitor', 'parts', 'accessory'];

export default function Settings() {
  const p = usePalette();
  const { me, updatePrefs, syncEntitlement, reload } = useSession();
  const invalidate = useInvalidateDeals();
  const [saving, setSaving] = useState(false);
  if (!me) return null;
  const pr = me.prefs;

  async function set(patch: Partial<Prefs>) {
    setSaving(true);
    try {
      await updatePrefs(patch);
      invalidate();
    } catch {
      Alert.alert('Enregistrement impossible', 'Vérifie ta connexion.');
    } finally {
      setSaving(false);
    }
  }

  // An empty list means "everything": tapping a chip then removes just that one.
  function toggleCat(c: Category) {
    const cur = new Set(pr.categories.length ? pr.categories : CATS);
    if (cur.has(c)) cur.delete(c);
    else cur.add(c);
    if (cur.size === 0) return; // keep at least one category
    set({ categories: cur.size === CATS.length ? [] : [...cur] });
  }

  async function onNotify(v: boolean) {
    await set({ notify: v });
    if (v && !(await enablePush().catch(() => false))) {
      Alert.alert('Notifications désactivées', 'Autorise-les dans les réglages du téléphone pour recevoir les alertes.');
    }
  }

  function deleteAccount() {
    Alert.alert(
      'Supprimer mon compte ?',
      'Tes réglages et favoris seront effacés. L’abonnement se gère et se résilie depuis ton compte App Store ou Google Play.',
      [
        { text: 'Annuler', style: 'cancel' },
        {
          text: 'Supprimer',
          style: 'destructive',
          onPress: async () => {
            await api('/v1/me', { method: 'DELETE' });
            await signOut();
            await reload();
          },
        },
      ],
    );
  }

  const until = me.entitlement.until ? new Date(me.entitlement.until) : null;
  const trackColor = { true: p.accent, false: p.border };

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: p.bg }} edges={['top']}>
      <ScrollView contentContainerStyle={s.wrap}>
        <View style={s.titleRow}>
          <T v="title">Réglages</T>
          {saving ? (
            <T v="small" color="muted">
              Enregistrement…
            </T>
          ) : null}
        </View>

        <SectionTitle>Point de départ</SectionTitle>
        <Row label={pr.home_label ?? 'Non renseigné'} detail="Modifier" onPress={() => router.push('/location')} />

        <SectionTitle>Jusqu’où tu te déplaces</SectionTitle>
        <View style={s.chips}>
          {RADII.map((r) => (
            <Chip key={r} label={`${r} km`} active={pr.radius_km === r} onPress={() => set({ radius_km: r })} />
          ))}
        </View>
        <View style={[s.switchRow, { marginTop: space.lg }]}>
          <View style={{ flex: 1, gap: 2 }}>
            <T v="strong">Inclure les annonces avec envoi</T>
            <T v="small" color="muted">
              Plus loin que ton rayon, si le vendeur expédie. Frais d’envoi déduits.
            </T>
          </View>
          <Switch value={pr.include_shipping} onValueChange={(v) => set({ include_shipping: v })} trackColor={trackColor} thumbColor={p.elevated} ios_backgroundColor={p.border} />
        </View>

        <SectionTitle>Bénéfice minimum</SectionTitle>
        <View style={s.chips}>
          {PROFITS.map((v) => (
            <Chip key={v} label={`${v} €`} active={pr.min_profit === v} onPress={() => set({ min_profit: v })} />
          ))}
        </View>
        <T v="small" color="faint" style={{ marginTop: space.sm }}>
          Pour les annonces lointaines, la marge et la certitude exigées restent plus élevées, quoi qu’il arrive.
        </T>

        <SectionTitle
          right={
            pr.categories.length ? (
              <Pressable onPress={() => set({ categories: [] })} hitSlop={8}>
                <T v="label" color="muted">
                  Tout cocher
                </T>
              </Pressable>
            ) : undefined
          }>
          Catégories
        </SectionTitle>
        <View style={s.chips}>
          {CATS.map((c) => (
            <Chip
              key={c}
              label={CATEGORY_LABEL[c]}
              active={pr.categories.length === 0 || pr.categories.includes(c)}
              onPress={() => toggleCat(c)}
              soft
            />
          ))}
        </View>

        <SectionTitle>Alertes</SectionTitle>
        <View style={s.switchRow}>
          <View style={{ flex: 1, gap: 2 }}>
            <T v="strong">Notifications</T>
            <T v="small" color="muted">
              Un message dès qu’une affaire correspond à tes critères. Jamais la nuit.
            </T>
          </View>
          <Switch value={pr.notify} onValueChange={onNotify} trackColor={trackColor} thumbColor={p.elevated} ios_backgroundColor={p.border} />
        </View>
        {pr.notify ? (
          <View style={[s.chips, { marginTop: space.md }]}>
            <Chip label="Dès qu’elles paraissent" active={pr.notify_mode !== 'daily'} onPress={() => set({ notify_mode: 'instant' })} />
            <Chip label="Un relevé le soir" active={pr.notify_mode === 'daily'} onPress={() => set({ notify_mode: 'daily' })} />
          </View>
        ) : null}

        <SectionTitle>Abonnement</SectionTitle>
        <T v="strong">TechFlip, abonnement actif</T>
        {until && until.getFullYear() < 2900 ? (
          <T v="small" color="muted">
            {`Renouvellement ou fin le ${until.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' })}`}
          </T>
        ) : null}
        <View style={{ marginTop: space.md }}>
          <Row label="Gérer ou résilier mon abonnement" onPress={() => manageSubscription().catch(() => undefined)} />
          <Rule />
          <Row
            label="Restaurer mes achats"
            onPress={async () => {
              try {
                await restore();
                await syncEntitlement();
              } catch {
                Alert.alert('Restauration impossible', 'Vérifie ta connexion et réessaie.');
              }
            }}
          />
        </View>

        <SectionTitle>À propos</SectionTitle>
        <Row label="Conditions d’utilisation" onPress={() => WebBrowser.openBrowserAsync(config.termsUrl)} />
        <Rule />
        <Row label="Confidentialité" onPress={() => WebBrowser.openBrowserAsync(config.privacyUrl)} />
        <Rule />
        <Row label="Supprimer mon compte" onPress={deleteAccount} danger />

        <T v="small" color="faint" style={{ textAlign: 'center', marginTop: space.xxl }}>
          {`TechFlip ${Application.nativeApplicationVersion ?? ''}`.trim()}
          {'\n'}Estimations indicatives : vérifie toujours avant d’acheter.
        </T>
      </ScrollView>
    </SafeAreaView>
  );
}

function Row({ label, detail, onPress, danger }: { label: string; detail?: string; onPress: () => void; danger?: boolean }) {
  return (
    <Pressable accessibilityRole="button" onPress={onPress} style={({ pressed }) => [s.row, { opacity: pressed ? 0.6 : 1 }]}>
      <T color={danger ? 'risk' : 'text'} style={{ flex: 1 }}>
        {label}
      </T>
      <T v="small" color="faint">
        {detail ?? '›'}
      </T>
    </Pressable>
  );
}

const s = StyleSheet.create({
  wrap: { padding: space.xl, paddingBottom: space.xxl * 2 },
  titleRow: { flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  switchRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md, paddingVertical: space.md },
});
