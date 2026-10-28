# Shipping TechFlip to the App Store and Google Play

Order matters: accounts first, then the server, then the app builds.

## 0. Accounts you need

| Account | Cost | Used for |
|---------|------|----------|
| Apple Developer Program | 99 USD/yr | App Store, App Attest, in-app subscriptions |
| Google Play Console | 25 USD once | Play Store, Play Integrity, subscriptions |
| Google Cloud project | free tier | Play Integrity decoding, Android Maps key |
| RevenueCat | free tier, then a revenue share (check current pricing) | Subscription receipts, webhooks |
| Expo (EAS) | free tier | Cloud builds, push notifications |
| A VPS + a domain | ~5 EUR/month | Scanner + API (`api.yourdomain`) |

## 1. Store products

1. **App Store Connect**: create the app (bundle id `fr.techflip.app` or yours),
   then a subscription group with two auto-renewing products, for example
   `techflip_monthly` and `techflip_annual`. Add a free trial as an introductory
   offer if you want one; the paywall shows it automatically.
2. **Play Console**: create the app (package `fr.techflip.app`) and the same two
   subscriptions.
3. **Apple Developer > Identifiers**: on the App ID, enable **App Attest**.

## 2. RevenueCat

1. Create a project, add both apps (App Store with the in-app purchase key,
   Play with a service account), and import the four products.
2. Create an entitlement named **`pro`** and attach all products to it.
3. Create an offering (mark it *current*) with an `Annual` and a `Monthly`
   package.
4. Project settings > **Restore behavior: Transfer to new App User ID**.
5. API keys: copy the **public** iOS (`appl_...`) and Android (`goog_...`) keys
   into `mobile/.env.local`, and a **secret** key (`sk_...`) into the server
   `.env` as `REVENUECAT_SECRET_KEY`.
6. Integrations > Webhooks: URL `https://api.yourdomain/v1/webhooks/revenuecat`,
   Authorization header value = a long random string, also set as
   `REVENUECAT_WEBHOOK_AUTH` on the server.

## 3. Play Integrity

1. Play Console > App integrity > **Link a Google Cloud project**. Note the
   project **number**, which goes in `EXPO_PUBLIC_PLAY_CLOUD_PROJECT`.
2. In that GCP project, enable the **Play Integrity API**, create a service
   account, download its JSON key to `secrets/play-integrity.json` on the server.
3. In the same project, create an **Android Maps SDK** key restricted to your
   package and signing certificate SHA-1, which goes in
   `EXPO_PUBLIC_ANDROID_MAPS_KEY`. (iOS uses Apple Maps, no key.)

## 4. Server

```bash
git clone <this repo> && cd TechFlipperFrance
cp .env.example .env            # fill in Telegram, JWT_SECRET, IOS_APP_ID, RevenueCat...
mkdir -p secrets && cp ~/play-integrity.json secrets/
scripts/fetch_apple_root.sh     # pins Apple's App Attestation root CA
# set your domain in deploy/Caddyfile, point its DNS at the VPS, then:
cd deploy && docker compose up -d --build
docker compose exec scanner python -m techflip.cli bootstrap   # warm the price tracker
curl https://api.yourdomain/v1/health
```

The compose file runs three containers sharing one SQLite database: `scanner`
(the Leboncoin/2ememain loop, with app pushes on), `api`, and `caddy` (HTTPS).

## 5. App builds

```bash
cd mobile
cp .env.example .env.local      # API URL, RevenueCat public keys, Play project number, Maps key
npm install
npx eas-cli@latest login
npx eas-cli@latest init         # writes the EAS project id; put it in EXPO_PUBLIC_EAS_PROJECT_ID
npx eas-cli@latest build --platform all --profile production
npx eas-cli@latest submit --platform all
```

EAS manages signing certificates and push credentials (APNs key / FCM) for you.

## 6. Local development

The iOS Simulator and Android emulators have no App Attest / Play Integrity and
cannot buy subscriptions, so local work uses an insecure dev mode on both ends:

```bash
# backend, attestation off, everyone unlocked (refuses to start otherwise)
JWT_SECRET=$(python -c 'import secrets;print(secrets.token_urlsafe(48))') \
ATTEST_MODE=off DEV_UNLOCK_ALL=1 python -m techflip.cli serve
```

```bash
# app: a development build pointing at it
cd mobile
EXPO_PUBLIC_API_URL=http://<your-lan-ip>:8000 EXPO_PUBLIC_INSECURE_DEV_AUTH=1 npx expo run:ios
```

To test the real flow (attestation + sandbox purchases), use a physical device
with an EAS `development` build against a staging server with
`ATTEST_MODE=enforce` and `IOS_ATTEST_ENV=development`.

## 7. Store review checklist

- Paywall shows price, period, trial terms, **Restaurer mes achats**, CGU and
  Confidentialité links (both are required by Apple). Host those two pages and set
  `EXPO_PUBLIC_TERMS_URL` / `EXPO_PUBLIC_PRIVACY_URL`.
- Account deletion is in Réglages (Apple guideline 5.1.1(v)).
- Location is asked "when in use" only, with a clear purpose string.
- Give Apple's reviewer a way in: they cannot pass your paywall with a real
  card. Either rely on sandbox purchases (the default for review builds) or
  grant a promotional entitlement in RevenueCat to the reviewer's account.
