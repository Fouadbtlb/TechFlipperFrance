# TechFlip Design

Self-hosted deal scanner for used tech (consoles, PCs, laptops, components,
phones, monitors) sold on Leboncoin. It polls searches, values each listing by
decomposing it into its components, prices those components from a local price
tracker it learns from the market itself, and alerts on Telegram when the net
profit clears a bar that gets stricter the farther the item is from Lille.

Fork of the `autoscan` used-car scanner; same pipeline shape (fetch -> store ->
filter -> value -> alert), retargeted at tech and re-centered on Lille.

## Core idea: value by decomposition, not by average price

A machine is never judged by its asking price against some "average PC". It is
valued by what its parts are worth. A 250 EUR "PC gamer" hiding an RTX 4070 is a
deal even if the case, PSU and drive are worthless.

    true_value = sum(component market value) * realization_factor * condition_mult

- `realization_factor` (default 0.85): what you actually clear reselling parts
  after friction.
- `condition_mult`: working = 1.0, unknown = ~0.7, broken/for-parts = salvage.
- Components we cannot recognize contribute 0 and lower the confidence of the
  estimate rather than inventing value.

## The local price tracker (the brain)

Per-component market prices, learned from the same listings the scanner scrapes.
This is `autoscan`'s "learn the median from what you scrape" idea, keyed per
component instead of per car model, then summed compositionally.

- `config/pricebook.yaml` catalog: canonical component keys (`gpu:rtx-4070`,
  `cpu:i5-12400f`, `console:ps5`, `ram:ddr4-16gb`, `ssd:nvme-1tb`, `psu:650w`,
  ...), each with match aliases and a seed price so day one is sane.
- The tracker learns from single-item listings (a standalone "RTX 4070" ad feeds
  the RTX 4070 price; a whole PC consumes prices, it does not feed them).
- Learned value is a recency-windowed median. It overrides the seed once a
  component has at least `MIN_COMPARABLES` recent observations, and blends near
  the threshold. Each lookup returns value, confidence, sample size, and whether
  the number came from seed, learned, or blend.

## Distance and logistics (Lille-centric)

`geo.py` maps a listing's postal code to lat/lng from an offline French postal
table (no external API), takes the haversine distance to Lille (50.63, 3.06),
and derives a zone plus a logistics cost.

- Pickup cost = round-trip km * cost-per-km (default 0.25 EUR).
- Shipping cost = per-item-class parcel estimate (console ~15, GPU ~10,
  full tower ~30 or not shippable).

    net_profit = true_value - asking_price - logistics_cost

## Alert decision: stricter the farther it is

| Zone   | Distance          | Net bar (EUR) | Analysis demanded                              |
|--------|-------------------|---------------|------------------------------------------------|
| EASY   | < 60 km           | 30            | thin evidence OK, cheap to go inspect          |
| MEDIUM | 60-150 km         | 80            | full decomposition + decent confidence         |
| HARD   | ship-only / >150  | 120           | decomposition + LLM/photo pass + risk vetting  |

The expensive local vision-LLM read, photo inspection and tech risk checks
(iCloud-locked, "for parts", bent pins, ex-mining card) are spent on far and
high-value deals and skipped on obvious cheap local ones. Every number here is
configuration.

## Search configuration split

`config/searches.yaml` holds two kinds of search:

- feeder: nationwide, single components, used only to teach the price tracker,
  never alert.
- hunt: PCs, bundles and anything near Lille (radius via the Leboncoin
  `locations` URL param) plus nationwide shippable listings, valued and alerted.

## Modules

Existing (kept, some fixed): `domain.py`, `config.py`, `storage.py`,
`filters.py`, `pipeline.py`, `cli.py`, `sources/`, `scoring/ai.py`,
`scoring/seller.py`, `notify/telegram.py`.

New:

- `pricing/catalog.py` loads and indexes the component catalog.
- `pricing/extract.py` turns a listing (title, description, later LLM output)
  into recognized components with quantities and attributes.
- `pricing/tracker.py` seed-plus-learned per-component pricing. Replaces the dead
  car `scoring/median.py`.
- `pricing/appraise.py` composes components into a `true_value` with confidence.
  Absorbs `scoring/appraisal.py`.
- `geo.py` postal -> distance to Lille -> zone and logistics cost.
- `data/fr_postal_latlng.csv` offline postal table.
- `config/pricebook.yaml` seed catalog.

## Storage changes

- Fix the `alerts` table so it matches what the alert writer stores.
- Store per-listing appraisal (true_value, net_profit, zone, confidence,
  component breakdown).
- Record per-component price observations for the tracker.

## Phases

- P0 Unbreak and rebrand: fix the alert-table crash and the dead median scorer,
  make `ScoreResult` consistent, drop car-field extraction, rename AutoScan ->
  TechFlip, fix the price floor/ceiling in filters. Runs end to end for consoles.
- P1 Valuation brain: catalog, extractor, tracker, appraiser wired into the
  pipeline. Values PCs, laptops, components and consoles.
- P2 Geo and tiered decisions: distance to Lille, logistics, tiered bars, and the
  feeder/hunt search split.
- P3 Enrichment and polish: LLM/photo pass and tech risk checks gated by zone,
  richer Telegram alert (zone, trip cost, component breakdown, confidence),
  tech-aware stats.

## Testing

The pure functions (extract, tracker, geo, appraise, decision) get unit tests so
valuations are checkable rather than assumed.

## Chosen defaults (all configurable)

realization_factor 0.85, EASY < 60 km at 30 EUR, MEDIUM 60-150 km at 80 EUR,
HARD ship-only / >150 km at 120 EUR, cost-per-km 0.25 EUR, MIN_COMPARABLES 5,
learned-price recency window 90 days.
