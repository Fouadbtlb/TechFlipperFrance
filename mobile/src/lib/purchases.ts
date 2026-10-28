import { Platform } from 'react-native';
import Purchases, { type PurchasesPackage } from 'react-native-purchases';

import { config } from './config';

// RevenueCat runs the store purchase. It is NOT what unlocks the app: the
// server re-checks RevenueCat with its secret key before serving any deal.

let configuredFor: string | null = null;

export function purchasesAvailable() {
  return Boolean(Platform.OS === 'ios' ? config.revenuecatIosKey : config.revenuecatAndroidKey);
}

export async function setupPurchases(appUserID: string) {
  if (!purchasesAvailable()) return;
  if (configuredFor === null) {
    Purchases.configure({
      apiKey: Platform.OS === 'ios' ? config.revenuecatIosKey : config.revenuecatAndroidKey,
      appUserID,
    });
  } else if (configuredFor !== appUserID) {
    await Purchases.logIn(appUserID);
  }
  configuredFor = appUserID;
}

export async function getPackages(): Promise<PurchasesPackage[]> {
  if (!purchasesAvailable()) return [];
  const offerings = await Purchases.getOfferings();
  const pkgs = offerings.current?.availablePackages ?? [];
  // annual first: it is the one we recommend
  const rank = (p: PurchasesPackage) => (p.packageType === 'ANNUAL' ? 0 : p.packageType === 'MONTHLY' ? 1 : 2);
  return [...pkgs].sort((a, b) => rank(a) - rank(b));
}

/** Returns false when the user cancelled the store sheet. */
export async function buy(pkg: PurchasesPackage): Promise<boolean> {
  try {
    await Purchases.purchasePackage(pkg);
    return true;
  } catch (e: any) {
    if (e?.userCancelled) return false;
    throw e;
  }
}

export async function restore() {
  await Purchases.restorePurchases();
}

export async function manageSubscription() {
  await Purchases.showManageSubscriptions();
}
