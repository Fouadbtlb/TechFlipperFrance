# TechFlip

Finds profitable used-tech deals on Leboncoin and 2ememain, values each listing
**part by part** against real market prices, and shows every subscriber the
deals that are profitable **from their own home**, after the drive or the
shipping. Ships as a paid iOS/Android app, with Telegram alerts for the owner.

```
 Leboncoin / 2ememain
        │  scanner (techflip.cli loop)
        ▼
 recognize parts ─► price each part (learned median) ─► appraisal (stored once)
        │                                                  │
        │                       per viewer: distance, logistics, personal bar
        ▼                                                  ▼
 Telegram (owner)                       API (techflip.cli serve) ─► mobile app
                                         ▲ attestation + RevenueCat entitlement
```

## Repository

| Path | What |
|------|------|
| `techflip/` | Scanner + valuation engine (Python) |
| `techflip/valuation.py` | What a listing is worth, in named steps with explicit rejections |
| `techflip/viewer.py` | Per-viewer decision: same listing, different profit per home |
| `techflip/tuning.py` | Every business rule you may want to adjust, in one file |
| `techflip/api/` | Paid-app backend: routes per domain, dependency chain, services |
| `mobile/` | Expo / React Native app (iOS + Android) |
| `deploy/` | Docker Compose + Caddy for a single VPS |
| `docs/ARCHITECTURE.md` | Where everything is and how to change it (French) |
| `docs/SECURITY.md` | Why a cracked app gets nothing |
| `docs/DEPLOY.md` | Step-by-step to the stores |
| `docs/DESIGN.md` | Valuation design |

## How a listing is valued

1. Recognize the components in the title/description against `config/pricebook.yaml`.
2. Price each one from the tracker: the median of real single-item listings
   (excluding the listing being valued), or a seed price until it has
   `MIN_COMPARABLES`.
3. `value = sum(parts × condition) × per-category quick-resale haircut`.
4. Far, uncertain, or easily faked items (single console/GPU/laptop/phone) get a
   local vision-LLM pass on the photos. The verdict is cached per price.
5. Seller trust (account age, reviews) is fetched once for candidates.

Then, **for each viewer**: `net = value − price − min(round-trip drive, shipping)`,
held to a bar that rises with distance (EASY < 60 km, MEDIUM < 150 km, HARD
beyond) plus that viewer's own minimum profit, radius and categories.

## The app

- **Affaires**: deals sorted by profit, distance or freshness, with category filters.
- **Carte**: profit pins around you, colored by distance zone, with a swipeable card carousel.
- **Fiche**: the full math (resale − price − trip), value part by part, confidence,
  photo check, seller trust, price drops, and one tap to the listing.
- **Alertes**: push notifications for new deals that match *your* criteria.
- **Paywall**: shows real, non-actionable proof ("12 affaires autour de Lille
  cette semaine, jusqu'à +210 €") before asking for money.

## Run it

```bash
pip install -e ".[dev]"
cp .env.example .env
scripts/check.sh                          # lint + 107 tests (+ app types and lint)
```

Scanner:

```bash
python -m techflip.cli check              # validate config + ping Telegram
python -m techflip.cli bootstrap          # warm up the price tracker
python -m techflip.cli loop               # run continuously (APP_BACKEND=1 to push to app users)
python -m techflip.cli health             # is the scanner alive, database counters
python -m techflip.cli top 15 60          # 15 best stored deals within 60 km of home
python -m techflip.cli price rtx 4070     # what the tracker thinks a part is worth
```

API (local dev, see `docs/DEPLOY.md` for production):

```bash
JWT_SECRET=$(python -c 'import secrets;print(secrets.token_urlsafe(48))') \
ATTEST_MODE=off DEV_UNLOCK_ALL=1 python -m techflip.cli serve
```

App:

```bash
cd mobile && npm install
EXPO_PUBLIC_API_URL=http://<lan-ip>:8000 EXPO_PUBLIC_INSECURE_DEV_AUTH=1 npx expo run:ios
npm run typecheck && npm run lint
```

## Before you sell this

Scraping Leboncoin breaks its terms of service, and in France reselling data
extracted from a marketplace can also infringe the database producer's
*sui generis* right (Code de la propriété intellectuelle, L342-1). Leboncoin has
gone to court over this before. Running it for yourself is one level of risk;
charging subscribers for it is another. Get a French IP lawyer's opinion, and
consider pointing the app at sources that allow it. Apple and Google may also
ask during review where the listings come from.

## License

Proprietary.
