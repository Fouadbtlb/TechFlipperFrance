import { config } from './config';
import { registerProof, refreshProof } from './integrity';
import { secure } from './secure';

// Thin client: short-lived access token in memory, rotating refresh token in the
// Keychain/Keystore. Every refresh re-proves the device (App Attest / Play
// Integrity), so a copied token is useless without the phone it lives on.

type Tokens = { user_id: string; device_id: string; access_token: string; refresh_token: string };

const REFRESH_KEY = 'tf.refresh';
const USER_KEY = 'tf.user';

export class ApiError extends Error {
  constructor(public status: number, public code: string, message?: string) {
    super(message || code);
  }
}

let access: string | null = null;
let userId: string | null = null;
let inflight: Promise<void> | null = null;

async function call(path: string, init: RequestInit = {}, token: string | null = access) {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (init.body) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${config.apiUrl}${path}`, { ...init, headers: { ...headers, ...(init.headers as object) } });
  let body: any = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return { res, body };
}

function fail(status: number, body: any): never {
  const d = body?.detail;
  throw new ApiError(status, d?.code ?? (typeof d === 'string' ? d : 'error'), d?.message);
}

async function challenge(): Promise<string> {
  const { res, body } = await call('/v1/auth/challenge', { method: 'POST' }, null);
  if (!res.ok) fail(res.status, body);
  return body.challenge;
}

async function store(t: Tokens) {
  access = t.access_token;
  userId = t.user_id;
  await secure.set(REFRESH_KEY, t.refresh_token);
  await secure.set(USER_KEY, t.user_id);
}

async function register(freshKey = false): Promise<void> {
  const ch = await challenge();
  const proof = await registerProof(ch, freshKey);
  const { res, body } = await call('/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify({ challenge: ch, ...proof }),
  }, null);
  if (res.status === 409 && !freshKey) return register(true); // reinstall kept an already-used key
  if (!res.ok) fail(res.status, body);
  await store(body);
}

async function refresh(): Promise<void> {
  const rt = await secure.get(REFRESH_KEY);
  if (!rt) return register();
  const ch = await challenge();
  const proof = await refreshProof(ch);
  const { res, body } = await call('/v1/auth/refresh', {
    method: 'POST',
    body: JSON.stringify({ refresh_token: rt, challenge: ch, ...proof }),
  }, null);
  if (res.status === 401 && ['session_expired', 'session_revoked'].includes(body?.detail?.code)) {
    await signOut();
    return register();
  }
  if (!res.ok) fail(res.status, body);
  await store(body);
}

function renew(): Promise<void> {
  if (!inflight) inflight = refresh().finally(() => (inflight = null));
  return inflight;
}

/** Make sure we hold a valid session; returns the user id (= RevenueCat app user id). */
export async function ensureSession(): Promise<string> {
  if (!access) await renew();
  return userId as string;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  await ensureSession();
  let { res, body } = await call(path, init);
  if (res.status === 401) {
    await renew();
    ({ res, body } = await call(path, init));
  }
  if (!res.ok) fail(res.status, body);
  return body as T;
}

export async function signOut() {
  access = null;
  userId = null;
  await secure.del(REFRESH_KEY);
  await secure.del(USER_KEY);
}
