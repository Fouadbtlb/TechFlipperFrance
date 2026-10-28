import * as SecureStore from 'expo-secure-store';

// THIS_DEVICE_ONLY: never synced to iCloud Keychain or restored onto another
// phone, so a session cannot be lifted off the device it was attested on.
const opts: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

export const secure = {
  get: (k: string) => SecureStore.getItemAsync(k, opts),
  set: (k: string, v: string) => SecureStore.setItemAsync(k, v, opts),
  del: (k: string) => SecureStore.deleteItemAsync(k, opts),
};
