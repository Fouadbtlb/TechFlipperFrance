import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query';
import * as Notifications from 'expo-notifications';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider, router } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { ActivityIndicator, AppState, Platform, StyleSheet, View, useColorScheme } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { Button, EmptyState } from '@/components/ui';
import { ApiError } from '@/lib/api';
import { SessionProvider, useSession } from '@/lib/session';
import { usePalette } from '@/lib/theme';

function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        retry: (n, e) => !(e instanceof ApiError && [401, 402, 404, 409, 429].includes(e.status)) && n < 2,
      },
    },
  });
}

function openFromNotification(resp: Notifications.NotificationResponse | null) {
  const uid = resp?.notification.request.content.data?.uid;
  if (typeof uid === 'string') router.push({ pathname: '/deal/[uid]', params: { uid } });
}

function Gate() {
  const { stage, error, reload, me } = useSession();
  const p = usePalette();

  // Coming back to the app: refetch lists and re-check the subscription so an
  // expiry or a renewal applies immediately.
  useEffect(() => {
    const sub = AppState.addEventListener('change', (st) => {
      focusManager.setFocused(st === 'active');
      if (st === 'active' && me) reload();
    });
    return () => sub.remove();
  }, [me, reload]);

  useEffect(() => {
    if (stage !== 'ready' || Platform.OS === 'web') return;
    try {
      openFromNotification(Notifications.getLastNotificationResponse());
    } catch {
      // a push that cannot be read must never take the app down
    }
    const sub = Notifications.addNotificationResponseReceivedListener(openFromNotification);
    return () => sub.remove();
  }, [stage]);

  if (stage === 'loading') {
    return (
      <View style={[styles.center, { backgroundColor: p.bg }]}>
        <ActivityIndicator color={p.profit} />
      </View>
    );
  }
  if (stage === 'error') {
    return (
      <View style={[styles.center, { backgroundColor: p.bg }]}>
        <EmptyState
          icon="cloud-offline-outline"
          title="Connexion impossible"
          body={error ?? undefined}
          action={<Button label="Réessayer" onPress={reload} style={{ marginTop: 8 }} />}
        />
      </View>
    );
  }

  return (
    <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: p.bg } }}>
      <Stack.Protected guard={stage === 'onboarding'}>
        <Stack.Screen name="onboarding" />
      </Stack.Protected>
      <Stack.Protected guard={stage === 'paywall'}>
        <Stack.Screen name="paywall" />
      </Stack.Protected>
      <Stack.Protected guard={stage === 'ready'}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen name="deal/[uid]" />
        <Stack.Screen name="location" options={{ presentation: 'modal' }} />
      </Stack.Protected>
    </Stack>
  );
}

export default function RootLayout() {
  const [client] = useState(makeClient);
  const scheme = useColorScheme();
  const p = usePalette();
  const base = scheme === 'light' ? DefaultTheme : DarkTheme;
  return (
    <SafeAreaProvider>
      <QueryClientProvider client={client}>
        <ThemeProvider
          value={{
            ...base,
            colors: { ...base.colors, background: p.bg, card: p.bg, text: p.text, border: p.border, primary: p.profit },
          }}>
          <SessionProvider>
            <StatusBar style={scheme === 'light' ? 'dark' : 'light'} />
            <Gate />
          </SessionProvider>
        </ThemeProvider>
      </QueryClientProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
});
