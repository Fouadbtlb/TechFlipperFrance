import * as AppIntegrity from '@expo/app-integrity';
import { Platform } from 'react-native';

import { config } from './config';
import { secure } from './secure';

// Proof that this request comes from our genuine, unmodified app on a real
// device. The server verifies it with Apple / Google; nothing here is trusted
// on its own. Each proof is bound to a single-use server challenge.

const KEY_ID = 'tf.attest.key';

export type RegisterProof =
  | { platform: 'ios'; key_id: string; attestation: string }
  | { platform: 'android'; integrity_token: string }
  | { platform: 'dev' };

export type RefreshProof = { assertion?: string; integrity_token?: string };

let androidReady: Promise<void> | null = null;

function prepareAndroid() {
  if (!androidReady) {
    androidReady = AppIntegrity.prepareIntegrityTokenProviderAsync(config.playCloudProjectNumber).catch(
      (e) => {
        androidReady = null;
        throw e;
      },
    );
  }
  return androidReady;
}

export async function registerProof(challenge: string, freshKey = false): Promise<RegisterProof> {
  if (config.insecureDevAuth) return { platform: 'dev' };
  if (Platform.OS === 'ios') {
    if (!AppIntegrity.isSupported) throw new Error('Cet appareil ne permet pas de vérifier l’application.');
    let keyId = freshKey ? null : await secure.get(KEY_ID);
    if (!keyId) {
      keyId = await AppIntegrity.generateKeyAsync();
      await secure.set(KEY_ID, keyId);
    }
    const attestation = await AppIntegrity.attestKeyAsync(keyId, challenge);
    return { platform: 'ios', key_id: keyId, attestation };
  }
  await prepareAndroid();
  return { platform: 'android', integrity_token: await AppIntegrity.requestIntegrityCheckAsync(challenge) };
}

export async function refreshProof(challenge: string): Promise<RefreshProof> {
  if (config.insecureDevAuth) return {};
  if (Platform.OS === 'ios') {
    const keyId = await secure.get(KEY_ID);
    if (!keyId) throw new Error('Session à renouveler, redémarre l’application.');
    return { assertion: await AppIntegrity.generateAssertionAsync(keyId, challenge) };
  }
  await prepareAndroid();
  return { integrity_token: await AppIntegrity.requestIntegrityCheckAsync(challenge) };
}
