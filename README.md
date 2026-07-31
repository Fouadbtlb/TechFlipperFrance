# TechFlip — Self-Hosted Tech-Flip Scanner

TechFlip polls Leboncoin for used tech (consoles, PCs, laptops, GPUs, CPUs, RAM,
storage, PSUs, monitors), values each listing by **decomposing it into its
parts**, prices those parts from a local tracker it learns from the market
itself, and alerts you on Telegram when the net profit clears a bar that gets
stricter the farther the item is from Lille.

It is built for **flipping near Lille**: a cheap machine hiding a good GPU is a
deal even if the rest is junk, and a far listing has to be worth the shipping.

## How it values a machine

1. Recognize the components in the title/description against `config/pricebook.yaml`.
2. Price each one from the tracker: the median of real single-item listings it
   has scraped, or a seed price until it has enough (`MIN_COMPARABLES`).
3. `true_value = sum(parts) * REALIZATION_FACTOR`, discounted per condition.
4. `net_profit = true_value - asking_price - logistics` (drive round-trip or
   shipping, whichever is cheaper).
5. Alert if net_profit clears the zone bar with enough confidence.

| Zone   | Distance to Lille | Net bar | Analysis |
|--------|-------------------|---------|----------|
| EASY   | < 60 km           | 30 EUR  | thin evidence OK, cheap to inspect |
| MEDIUM | 60-150 km         | 80 EUR  | full decomposition + confidence |
| HARD   | > 150 km / ship   | 120 EUR | decomposition + LLM/photo + risk vetting |

Everything above is configurable in `.env`. Full design: [docs/DESIGN.md](docs/DESIGN.md).

## Install

```bash
pip install -e .
cp .env.example .env      # fill in the Telegram token
```

`pgeocode` (a dependency) downloads the French postal database on first use so
distances to Lille are exact; without it, TechFlip falls back to a small
built-in table and treats unknown locations as far.

## Configure

Edit `config/searches.yaml`. Two kinds of search:

- `hunt`: valued and can alert (near Lille = low bar, far = high bar).
- `feeder`: only teaches the price tracker, never alerts.

Distance is handled by the zone logic, so hunt searches can stay nationwide.

## Run

```bash
python -m techflip.cli check              # validate config + ping Telegram
python -m techflip.cli bootstrap          # warm up the price tracker
python -m techflip.cli once               # one test cycle
python -m techflip.cli loop               # run continuously
python -m techflip.cli price rtx 4070     # what the tracker thinks a part is worth
python -m techflip.cli try "pc gamer"     # value live listings for a query (no alert)
python -m techflip.cli top [n]            # best stored deals
python -m techflip.cli stats              # DB counters
```

## The first few days

The tracker refuses to trust a learned price without `MIN_COMPARABLES` real
single-item listings; until then it uses the seed prices in `pricebook.yaml`.
`bootstrap` and `feeder` searches fill it in faster.

## Local AI (optional)

For far or uncertain deals, a local vision model reads the description and photos
to confirm condition, count bundle extras, and flag tech scams (iCloud-locked,
ex-mining GPU, box-only, bent pins). For near-Lille listings the catalog cannot
decompose (laptops, phones, prebuilts), it also estimates a whole-item resale
value so they can still surface. It is never blocking: if the AI server is
offline, decomposable deals still alert. Backend swappable via `AI_URL`.

## Anti-blocking

Mobile TLS fingerprint matching the app user-agent, jittered intervals, night
pause, and a hard abort on the first DataDome block.

## License

Proprietary. See [LICENSE](LICENSE).
