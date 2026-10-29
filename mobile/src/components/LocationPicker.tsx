import * as Location from 'expo-location';
import { useState } from 'react';
import { Platform, StyleSheet, TextInput, View } from 'react-native';

import { ApiError, api } from '@/lib/api';
import { font, radius, space, usePalette } from '@/lib/theme';

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

type Hit = { lat: number; lng: number; label: string };

// The phone's geocoder first; TechFlip's own lookup (French and Belgian towns
// and postcodes) when there is none (the web build) or it finds nothing.
async function geocode(q: string): Promise<Hit | null> {
  if (Platform.OS !== 'web') {
    try {
      const [hit] = await Location.geocodeAsync(`${q}, France`);
      if (hit) {
        const label = /^\d{4,5}$/.test(q) ? await labelFor(hit.latitude, hit.longitude) : q.charAt(0).toUpperCase() + q.slice(1);
        return { lat: hit.latitude, lng: hit.longitude, label };
      }
    } catch {
      // fall through to the server lookup
    }
  }
  try {
    return await api<Hit>(`/v1/me/places?q=${encodeURIComponent(q)}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
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
      const hit = await geocode(q);
      if (!hit) {
        setErr('Lieu introuvable.');
        return;
      }
      await onPick({ home_lat: round(hit.lat), home_lng: round(hit.lng), home_label: hit.label });
    } catch {
      setErr('Recherche indisponible, réessaie.');
    } finally {
      setBusy(null);
    }
  }

  return (
    <View style={{ gap: space.md }}>
      <Button label={cta} onPress={fromGps} loading={busy === 'gps'} />
      <View style={[s.inputRow, { borderColor: p.border, backgroundColor: p.surface }]}>
        <TextInput
          value={query}
          onChangeText={setQuery}
          placeholder="Ou ta ville, ton code postal"
          placeholderTextColor={p.textFaint}
          returnKeyType="search"
          onSubmitEditing={fromSearch}
          autoCorrect={false}
          style={[s.input, { color: p.text }]}
        />
        {query ? <Button label="Valider" kind="ghost" onPress={fromSearch} loading={busy === 'search'} style={s.ok} /> : null}
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
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    flexDirection: 'row',
    alignItems: 'center',
    paddingLeft: space.lg,
  },
  input: { flex: 1, fontSize: 16, fontFamily: font.sans, height: '100%' },
  ok: { height: 40, paddingHorizontal: space.lg },
});
