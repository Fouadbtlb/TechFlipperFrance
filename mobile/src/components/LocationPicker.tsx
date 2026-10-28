import { Ionicons } from '@expo/vector-icons';
import * as Location from 'expo-location';
import { useState } from 'react';
import { StyleSheet, TextInput, View } from 'react-native';

import { radius, space, usePalette } from '@/lib/theme';

import { Button, T } from './ui';

export type Place = { home_lat: number; home_lng: number; home_label: string };

// ~1 km precision is all the distance math needs; the exact position never
// leaves the phone.
const round = (x: number) => Math.round(x * 100) / 100;

async function labelFor(lat: number, lng: number): Promise<string> {
  try {
    const [a] = await Location.reverseGeocodeAsync({ latitude: lat, longitude: lng });
    return a?.city || a?.subregion || a?.region || 'Ma position';
  } catch {
    return 'Ma position';
  }
}

export function LocationPicker({ onPick, cta = 'Utiliser ma position' }: { onPick: (p: Place) => Promise<void> | void; cta?: string }) {
  const p = usePalette();
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState<'gps' | 'search' | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function fromGps() {
    setErr(null);
    setBusy('gps');
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        setErr('Position refusée. Entre plutôt ta ville ou ton code postal.');
        return;
      }
      const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      const lat = round(pos.coords.latitude);
      const lng = round(pos.coords.longitude);
      await onPick({ home_lat: lat, home_lng: lng, home_label: await labelFor(lat, lng) });
    } catch {
      setErr('Impossible de te localiser. Entre ta ville ou ton code postal.');
    } finally {
      setBusy(null);
    }
  }

  async function fromSearch() {
    const q = query.trim();
    if (!q) return;
    setErr(null);
    setBusy('search');
    try {
      const [hit] = await Location.geocodeAsync(`${q}, France`);
      if (!hit) {
        setErr('Lieu introuvable.');
        return;
      }
      const lat = round(hit.latitude);
      const lng = round(hit.longitude);
      const label = /^\d{5}$/.test(q) ? await labelFor(lat, lng) : q.charAt(0).toUpperCase() + q.slice(1);
      await onPick({ home_lat: lat, home_lng: lng, home_label: label });
    } catch {
      setErr('Recherche indisponible, réessaie.');
    } finally {
      setBusy(null);
    }
  }

  return (
    <View style={{ gap: space.md }}>
      <Button label={cta} icon="navigate" onPress={fromGps} loading={busy === 'gps'} />
      <View style={[s.inputRow, { backgroundColor: p.surface, borderColor: p.border }]}>
        <Ionicons name="search" size={18} color={p.textMuted} />
        <TextInput
          value={query}
          onChangeText={setQuery}
          placeholder="Ou ta ville / code postal"
          placeholderTextColor={p.textFaint}
          returnKeyType="search"
          onSubmitEditing={fromSearch}
          autoCorrect={false}
          style={[s.input, { color: p.text }]}
        />
        {query ? <Button label="OK" kind="ghost" onPress={fromSearch} loading={busy === 'search'} style={s.ok} /> : null}
      </View>
      {err ? (
        <T v="small" color="warn">
          {err}
        </T>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  inputRow: {
    height: 52,
    borderRadius: radius.lg,
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
    alignItems: 'center',
    paddingLeft: space.lg,
    gap: space.sm,
  },
  input: { flex: 1, fontSize: 16, height: '100%' },
  ok: { height: 40, paddingHorizontal: space.lg },
});
