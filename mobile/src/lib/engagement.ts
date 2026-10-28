import * as Notifications from 'expo-notifications';
import * as StoreReview from 'expo-store-review';
import { Platform } from 'react-native';

import { secure } from './secure';

// Small, honest engagement mechanics. Each one either saves the user from a
// bad surprise (trial reminder) or asks at a moment that respects them
// (push primer after they have seen deals, rating after they acted on one).

const PRIMER_DISMISSED = 'tf.primer.dismissedAt';
const OPENED = 'tf.listings.opened';
const REVIEW_ASKED = 'tf.review.askedAt';

const DAY = 86_400_000;

// ---------- push primer ----------

/** Show our own explainer card only while the one-shot iOS prompt is unused. */
export async function shouldShowPushPrimer(): Promise<boolean> {
  if (Platform.OS === 'web') return false;
  const { status, canAskAgain } = await Notifications.getPermissionsAsync();
  if (status === 'granted' || !canAskAgain) return false;
  const dismissed = Number((await secure.get(PRIMER_DISMISSED)) ?? 0);
  return Date.now() - dismissed > 3 * DAY;
}

export async function dismissPushPrimer() {
  await secure.set(PRIMER_DISMISSED, String(Date.now()));
}

// ---------- rating prompt ----------

/**
 * Called when the user comes back from a listing they opened: they just acted
 * on a deal, the best moment to ask. Asks only after 3 different listings on 2+
 * different days, and at most every 4 months (Apple also caps it at 3 a year).
 */
export async function noteListingOpened(uid: string) {
  if (Platform.OS === 'web') return;
  const raw = await secure.get(OPENED);
  const opened: Record<string, number> = raw ? JSON.parse(raw) : {};
  opened[uid] = opened[uid] ?? Date.now();
  const entries = Object.entries(opened).sort((a, b) => b[1] - a[1]).slice(0, 20);
  await secure.set(OPENED, JSON.stringify(Object.fromEntries(entries)));

  const days = new Set(entries.map(([, t]) => new Date(t).toDateString()));
  const asked = Number((await secure.get(REVIEW_ASKED)) ?? 0);
  if (entries.length >= 3 && days.size >= 2 && Date.now() - asked > 120 * DAY) {
    if (await StoreReview.isAvailableAsync()) {
      await secure.set(REVIEW_ASKED, String(Date.now()));
      await StoreReview.requestReview();
    }
  }
}

// ---------- free-trial reminder ----------

const UNIT_DAYS: Record<string, number> = { DAY: 1, WEEK: 7, MONTH: 30, YEAR: 365 };

export function trialEnd(periodUnit: string, units: number, from = new Date()): Date {
  const d = new Date(from);
  if (periodUnit === 'MONTH') d.setMonth(d.getMonth() + units);
  else if (periodUnit === 'YEAR') d.setFullYear(d.getFullYear() + units);
  else d.setDate(d.getDate() + units * (UNIT_DAYS[periodUnit] ?? 1));
  return d;
}

/** The day we remind: 2 days before the first charge (1 for very short trials). */
export function reminderDate(end: Date, from = new Date()): Date {
  const totalDays = (end.getTime() - from.getTime()) / DAY;
  const d = new Date(end.getTime() - (totalDays > 4 ? 2 : 1) * DAY);
  d.setHours(10, 0, 0, 0);
  return d;
}

/** Local notification on this phone; nothing is sent to our server. */
export async function scheduleTrialReminder(end: Date, priceString: string) {
  if (Platform.OS === 'web') return;
  let { status } = await Notifications.getPermissionsAsync();
  if (status !== 'granted') ({ status } = await Notifications.requestPermissionsAsync());
  if (status !== 'granted') return;
  const when = reminderDate(end);
  if (when.getTime() <= Date.now()) return;
  await Notifications.scheduleNotificationAsync({
    content: {
      title: 'Ton essai gratuit se termine bientôt',
      body: `Premier paiement de ${priceString} le ${end.toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' })}. Tu peux résilier d’ici là depuis Réglages, sans frais.`,
    },
    trigger: { type: Notifications.SchedulableTriggerInputTypes.DATE, date: when },
  });
}
