# Security model: paid users only, nothing worth cracking

## The honest premise

No app can be made "unjailbreakable" or uncrackable. Anything shipped to a phone
can be decompiled, patched, and re-signed, and jailbreaks/roots exist for most
devices. Apps that try to win on the device (obfuscation, jailbreak detection)
lose to anyone motivated.

So TechFlip does not try to win on the device. **The app contains nothing of
value.** The scanner, the pricebook, the tracker, the valuations and the deals
all live on the server. The app is a viewer. A cracked app that thinks it is
"Pro" still gets nothing, because the server decides, on every request, whether
this user has paid.

## Layers

| # | Layer | Stops | Where |
|---|-------|-------|-------|
| 1 | All data and logic server-side | Reverse engineering the valuation, offline cracks | `techflip/` (never shipped) |
| 2 | Server-side entitlement via RevenueCat secret key | Patched "isPro = true" clients, fake receipts | `api/entitlements.py` |
| 3 | Device attestation at signup **and every token refresh** | Scripts/bots calling the API, repackaged APK/IPA, emulators, rooted Android | `api/attest.py` |
| 4 | 15-min access tokens, rotating single-use refresh tokens, reuse detection | Stolen or copied tokens | `api/accounts.py`, `api/app.py` |
| 5 | Device-bound storage (`WHEN_UNLOCKED_THIS_DEVICE_ONLY`, `allowBackup=false`) | Lifting a session to another phone via backup | `mobile/src/lib/secure.ts`, `app.config.ts` |
| 6 | Per-user rate limit + daily detail cap | A paying account bulk-scraping to resell | `api/app.py` |
| 7 | Teaser endpoint returns counts only | Free users seeing actionable data | `api/deals.py::teaser` |

### 2. Entitlement

The app buys through RevenueCat (StoreKit / Play Billing). That only tells
*RevenueCat* the user paid. Our server then asks RevenueCat directly with a
**secret** key (`sk_...`) that never ships in the app, and stores
`entitled_until`. Every paid endpoint checks it. There is no endpoint that
accepts an entitlement from the client (see the `test_client_cannot_self_grant`
test).

Freshness: RevenueCat's webhook (authenticated by a shared `Authorization`
header) triggers a re-fetch on every renewal, cancellation, refund, billing
issue or transfer. If a webhook is missed, an expired user is re-checked at
most every 6 hours on access.

### 3. Attestation

- **iOS, App Attest.** At signup the app creates a key in the Secure Enclave and
  Apple certifies it belongs to our App ID (`TEAMID.bundle`), in the production
  environment. The server verifies the certificate chain to Apple's root, the
  nonce binding to our single-use challenge, the App ID hash, the key id, and a
  zero counter. Every refresh is then a signature by that key over a new
  challenge, with a strictly increasing counter, so replays and cloned keys are
  rejected.
- **Android, Play Integrity (Standard API).** Every signup and refresh sends a
  token bound to our challenge (`requestHash`). The server decodes it with
  Google and requires `PLAY_RECOGNIZED` (unmodified binary from Play),
  `MEETS_DEVICE_INTEGRITY` (certified, not rooted, not an emulator), and
  `LICENSED` (installed from Play).

Attestation is checked at signup and at each token refresh (every 15 minutes),
not on every request. That keeps latency and Apple/Google quotas low, and a
token lifted off a device dies within 15 minutes because it cannot be renewed
without that device.

### 4. Tokens

- Access token: HS256 JWT, 15 minutes, carries user and device id.
- Refresh token: random, stored hashed, single use, rotated on every refresh,
  bound to the device. Presenting a used refresh token revokes the whole session
  family: the thief and the victim are both logged out and the victim silently
  re-authenticates with their device. The device proof is verified *before* the
  token is consumed, so a failed proof cannot burn a legitimate client's token.

### Account sharing

One install creates one anonymous account bound to one device. "Restaurer mes
achats" on another phone moves the subscription to that phone's account. Set
RevenueCat's **Restore behavior** to *Transfer to new App User ID*, so a
subscription is only ever active on one account at a time.

## What this does not stop

- A paying user telling friends about a deal or screenshotting it. Daily caps
  limit the scale; nothing technical prevents a human from sharing.
- iOS App Attest proves the app is genuine, not that the phone isn't
  jailbroken. A jailbroken iPhone running our genuine app still only sees what
  its paid account is allowed to see, within rate limits. Adding a jailbreak
  detection library would be cosmetic.
- Devices without App Attest (`isSupported == false`, rare and old) cannot sign
  up. This is a product decision. The alternative is a restricted fallback tier.

## Operations

- Ban a user: `UPDATE users SET status='banned' WHERE id=?`. Their access token
  stops working on the next request and they cannot refresh.
- Log everyone out: rotate `JWT_SECRET` and `DELETE FROM refresh_tokens`.
- Watch the `detail ceiling hit` and `refresh token reuse` log lines: they are
  your scraping and token-theft signals.
- `ATTEST_MODE=off` and `DEV_UNLOCK_ALL=1` exist for local simulator work only.
  The server refuses to start with `DEV_UNLOCK_ALL` unless attestation is off,
  and logs a warning whenever attestation is off.

## Possible additions

- TLS certificate pinning in the app (adds rotation risk; the security does not
  depend on it, since a MITM on your own phone still needs a valid attested
  device and a paid account).
- Apple's fraud-metric receipt (`devices.receipt` is already stored) to detect
  one device farming many accounts.
