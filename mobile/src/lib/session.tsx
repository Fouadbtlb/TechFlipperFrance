import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { ApiError, api, ensureSession } from './api';
import { setupPurchases } from './purchases';
import type { Me, Prefs } from './types';

type Stage = 'loading' | 'error' | 'onboarding' | 'paywall' | 'ready';

type Session = {
  stage: Stage;
  me: Me | null;
  error: string | null;
  reload: () => Promise<void>;
  updatePrefs: (p: Partial<Prefs>) => Promise<Me>;
  syncEntitlement: () => Promise<Me>;
  setMe: (m: Me) => void;
};

const Ctx = createContext<Session | null>(null);

function errorText(e: unknown): string {
  // fetch() rejects with an English TypeError when offline
  if (e instanceof ApiError || (e instanceof Error && /[àâçéèêëîïôûù]/i.test(e.message))) return e.message;
  return 'Vérifie ta connexion internet et réessaie.';
}

async function loadMe(): Promise<Me> {
  const uid = await ensureSession();
  await setupPurchases(uid).catch(() => undefined);
  return api<Me>('/v1/me');
}

function stageOf(me: Me | null): Stage {
  if (!me) return 'loading';
  if (me.prefs.home_lat == null) return 'onboarding';
  if (!me.entitlement.active) return 'paywall';
  return 'ready';
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setMe(await loadMe());
      setError(null);
    } catch (e: any) {
      setError(errorText(e));
    }
  }, []);

  useEffect(() => {
    let alive = true;
    loadMe()
      .then((m) => alive && setMe(m))
      .catch((e) => alive && setError(errorText(e)));
    return () => {
      alive = false;
    };
  }, []);

  const updatePrefs = useCallback(async (p: Partial<Prefs>) => {
    const next = await api<Me>('/v1/me/prefs', { method: 'PATCH', body: JSON.stringify(p) });
    setMe(next);
    return next;
  }, []);

  const syncEntitlement = useCallback(async () => {
    const next = await api<Me>('/v1/me/entitlement/sync', { method: 'POST' });
    setMe(next);
    return next;
  }, []);

  const value = useMemo<Session>(
    () => ({
      stage: error && !me ? 'error' : stageOf(me),
      me,
      error,
      reload,
      updatePrefs,
      syncEntitlement,
      setMe,
    }),
    [me, error, reload, updatePrefs, syncEntitlement],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession() {
  const s = useContext(Ctx);
  if (!s) throw new Error('useSession outside SessionProvider');
  return s;
}
