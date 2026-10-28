import { Ionicons } from '@expo/vector-icons';
import * as Application from 'expo-application';
import { router } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { Alert, Pressable, ScrollView, StyleSheet, Switch, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { Card, Chip, SectionTitle, T, type IconName } from '@/components/ui';
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
      Alert.alert('Notifications désactivées', "Autorise-les dans les réglages du téléphone pour recevoir les alertes.");
    }
  }

  function deleteAccount() {
    Alert.alert(
      'Supprimer mon compte ?',
      "Tes réglages et favoris seront effacés. L’abonnement se gère et s’annule depuis ton compte App Store / Google Play.",
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

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: p.bg }} edges={['top']}>
      <ScrollView contentContainerStyle={s.wrap}>
        <View style={s.titleRow}>
          <T v="title">Réglages</T>
          {saving ? <T v="small" color="muted">Enregistrement…</T> : null}
        </View>

        <SectionTitle>Point de départ</SectionTitle>
        <Row icon="navigate-outline" label={pr.home_label ?? '—'} onPress={() => router.push('/location')} chevron />

        <SectionTitle>Jusqu’où tu te déplaces</SectionTitle>
        <View style={s.chips}>
          {RADII.map((r) => (
            <Chip key={r} label={`${r}\u00a0km`} active={pr.radius_km === r} onPress={() => set({ radius_km: r })} />
          ))}
        </View>
        <Card style={{ marginTop: space.md }}>
          <View style={s.switchRow}>
            <View style={{ flex: 1, gap: 2 }}>
              <T style={{ fontWeight: '600' }}>Inclure les annonces avec envoi</T>
              <T v="small" color="muted">
                Plus loin que ton rayon, si le vendeur expédie. Frais d’envoi déduits.
              </T>
            </View>
            <Switch value={pr.include_shipping} onValueChange={(v) => set({ include_shipping: v })} trackColor={{ true: p.profit }} />
          </View>
        </Card>

        <SectionTitle>Bénéfice minimum</SectionTitle>
        <View style={s.chips}>
          {PROFITS.map((v) => (
            <Chip key={v} label={`${v}\u00a0€`} active={pr.min_profit === v} onPress={() => set({ min_profit: v })} />
          ))}
        </View>
        <T v="small" color="faint" style={{ marginTop: space.sm }}>
          Pour les annonces lointaines, on exige plus de marge et plus de certitude, quoi qu’il arrive.
        </T>

        <SectionTitle right={pr.categories.length ? <Pressable onPress={() => set({ categories: [] })}><T v="small" color="muted">Tout</T></Pressable> : undefined}>
          Catégories
        </SectionTitle>
        <View style={s.chips}>
          {CATS.map((c) => (
            <Chip
              key={c}
              label={CATEGORY_LABEL[c]}
              active={pr.categories.length === 0 || pr.categories.includes(c)}
              onPress={() => toggleCat(c)}
            />
          ))}
        </View>

        <SectionTitle>Alertes</SectionTitle>
        <Card>
          <View style={s.switchRow}>
            <View style={{ flex: 1, gap: 2 }}>
              <T style={{ fontWeight: '600' }}>Notifications</T>
              <T v="small" color="muted">
                Une alerte dès qu’une affaire correspond à tes critères.
              </T>
            </View>
            <Switch value={pr.notify} onValueChange={onNotify} trackColor={{ true: p.profit }} />
          </View>
        </Card>

        <SectionTitle>Abonnement</SectionTitle>
        <Card style={{ gap: space.md }}>
          <View style={s.switchRow}>
            <Ionicons name="checkmark-circle" size={20} color={p.profit} />
            <T style={{ flex: 1, fontWeight: '600' }}>TechFlip Pro actif</T>
            {until && until.getFullYear() < 2900 ? (
              <T v="small" color="muted">
                jusqu’au {until.toLocaleDateString('fr-FR')}
              </T>
            ) : null}
          </View>
        </Card>
        <Row icon="card-outline" label="Gérer ou résilier mon abonnement" onPress={() => manageSubscription().catch(() => undefined)} chevron />
        <Row
          icon="refresh-outline"
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

        <SectionTitle>À propos</SectionTitle>
        <Row icon="document-text-outline" label="Conditions d’utilisation" onPress={() => WebBrowser.openBrowserAsync(config.termsUrl)} chevron />
        <Row icon="lock-closed-outline" label="Confidentialité" onPress={() => WebBrowser.openBrowserAsync(config.privacyUrl)} chevron />
        <Row icon="trash-outline" label="Supprimer mon compte" onPress={deleteAccount} danger />

        <T v="tiny" color="faint" style={{ textAlign: 'center', marginTop: space.xl }}>
          TechFlip {Application.nativeApplicationVersion ?? ''} · Estimations indicatives, vérifie toujours avant d’acheter.
        </T>
      </ScrollView>
    </SafeAreaView>
  );
}

function Row({
  icon,
  label,
  onPress,
  chevron,
  danger,
}: {
  icon: IconName;
  label: string;
  onPress: () => void;
  chevron?: boolean;
  danger?: boolean;
}) {
  const p = usePalette();
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [s.row, { backgroundColor: p.surface, borderColor: p.border, opacity: pressed ? 0.8 : 1 }]}>
      <Ionicons name={icon} size={19} color={danger ? p.risk : p.textMuted} />
      <T style={{ flex: 1, fontWeight: '600' }} color={danger ? 'risk' : 'text'}>
        {label}
      </T>
      {chevron ? <Ionicons name="chevron-forward" size={17} color={p.textFaint} /> : null}
    </Pressable>
  );
}

const s = StyleSheet.create({
  wrap: { padding: space.lg, paddingBottom: space.xxl * 2 },
  titleRow: { flexDirection: 'row', alignItems: 'flex-end', justifyContent: 'space-between' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  switchRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
    padding: space.lg,
    borderRadius: 14,
    borderWidth: StyleSheet.hairlineWidth,
    marginBottom: space.sm,
  },
});
