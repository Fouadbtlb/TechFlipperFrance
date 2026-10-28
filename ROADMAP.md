# Roadmap

## Done
- Component-decomposition valuation with a learned per-part tracker. A listing
  no longer counts as its own comparable.
- Per-viewer decisions: one stored appraisal, profit computed from each user's
  home, radius, minimum profit and categories (`techflip/viewer.py`).
- Vision-LLM verdict cached per price (the resweep used to re-run it every cycle).
- Price history and price-drop badges.
- Seller trust wired in (account age, reviews, scam pattern raises risk).
- Postal lookup no longer crashes the scanner when its download fails.
- Paid-app backend: App Attest / Play Integrity, rotating device-bound tokens,
  RevenueCat entitlements + webhook, rate limits, push fanout, teaser endpoint.
- Expo app: onboarding, paywall, feed, map, deal sheet, favorites, settings.
- Departed listings re-checked and used as near-sale prices, with time to sell;
  dead deals leave the feed on their own.
- Subscribers rate estimates (too low / fair / too high) and report resale
  prices: bounded crowd correction (+/-10 %, 5+ different people) and real
  sales for the tracker.
- Price floor ("même revendu au plus bas"), reliable vs "à vérifier" buckets,
  repost detection, negotiation helper, evening digest option.

## Next
- Grow `config/pricebook.yaml` (cases/PSUs/motherboards are still uncounted).
- Departure checks for 2ememain (Leboncoin only today).
- Postgres when concurrent subscribers outgrow SQLite WAL.
- "Mark as bought" + realized profit tracking in the app (flip journal).
- Saved searches with their own alert bars.

## Ideas
- Apple fraud-metric receipts to spot one device farming accounts.
- More sources behind `techflip/sources/` (sources that permit reuse first).
