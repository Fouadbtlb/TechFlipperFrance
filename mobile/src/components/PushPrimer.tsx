import * as Notifications from 'expo-notifications';
import { useEffect, useState } from 'react';
import { Platform, StyleSheet, View } from 'react-native';

import { dismissPushPrimer, shouldShowPushPrimer } from '@/lib/engagement';
import { enablePush } from '@/lib/notifications';
import { radius, space, usePalette } from '@/lib/theme';

import { Button, T } from './ui';

/**
 * iOS shows the system permission prompt only once. Instead of firing it on
 * launch, this note explains the concrete benefit next to real deals, and the
 * system prompt only appears when the user taps "Activer".
 * When permission is already granted, it just (re)registers the push token.
 */
export function PushPrimer() {
  const p = usePalette();
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (Platform.OS === 'web') return;
    let alive = true;
    Notifications.getPermissionsAsync()
      .then(async ({ status }) => {
        if (status === 'granted') {
          await enablePush();
          return;
        }
        if (alive) setShow(await shouldShowPushPrimer());
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  if (!show) return null;
  return (
    <View style={[s.card, { borderColor: p.brass, backgroundColor: p.tint }]}>
      <T v="h2">Les bonnes affaires partent vite</T>
      <T color="muted">Active les alertes : un message dès qu’une affaire rentable pour toi est publiée.</T>
      <View style={s.row}>
        <Button
          label="Activer"
          loading={busy}
          style={s.btn}
          onPress={async () => {
            setBusy(true);
            await enablePush().catch(() => false);
            setBusy(false);
            setShow(false);
          }}
        />
        <Button
          label="Plus tard"
          kind="ghost"
          style={s.btn}
          onPress={() => {
            dismissPushPrimer();
            setShow(false);
          }}
        />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  card: { borderRadius: radius.md, borderWidth: StyleSheet.hairlineWidth, padding: space.lg, gap: space.sm },
  row: { flexDirection: 'row', gap: space.md, alignItems: 'center', marginTop: space.sm },
  btn: { flex: 1, height: 44 },
});
