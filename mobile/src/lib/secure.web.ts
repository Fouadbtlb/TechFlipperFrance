// Web preview only (the store apps use the Keychain/Keystore via secure.ts).
export const secure = {
  get: async (k: string) => globalThis.localStorage?.getItem(k) ?? null,
  set: async (k: string, v: string) => globalThis.localStorage?.setItem(k, v),
  del: async (k: string) => globalThis.localStorage?.removeItem(k),
};
