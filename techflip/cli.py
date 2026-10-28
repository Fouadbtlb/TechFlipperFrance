"""CLI.

  python -m techflip.cli check              validate config, ping Telegram
  python -m techflip.cli once               one polling cycle (good first test)
  python -m techflip.cli loop               run the scanner forever (+ app pushes)
  python -m techflip.cli serve [port]       run the app API (default 8000)
  python -m techflip.cli bootstrap [pages]  one-shot market warm-up (default 3)
  python -m techflip.cli top [n]            best stored deals, in the terminal
  python -m techflip.cli price <query>      what the tracker thinks a part is worth
  python -m techflip.cli try <query>        value live listings for a query (no alert)
  python -m techflip.cli stats              DB counters
"""
from __future__ import annotations

import logging
import os
import sys

from .config import SearchConfig, load_api_settings, load_settings
from .domain import Listing, ScoreResult
from .pipeline import Pipeline
from .pricing.appraise import appraise, build_items
from .pricing.catalog import load_catalog
from .pricing.extract import extract_components
from .pricing.tracker import PriceTracker
from .storage import Store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "loop"
    settings = load_settings()

    if cmd in ("once", "loop", "bootstrap", "check") and not settings.searches:
        print("Aucune recherche dans config/searches.yaml — ajoute au moins une URL Leboncoin.")
        sys.exit(1)

    if cmd == "check":
        hunts = [s for s in settings.searches if s.kind == "hunt"]
        feeders = [s for s in settings.searches if s.kind == "feeder"]
        print(f"{len(hunts)} recherche(s) hunt, {len(feeders)} feeder:")
        for s in settings.searches:
            print(f"  - [{s.kind}] {s.name}")
        p = Pipeline(settings)
        fake = Listing(
            source="leboncoin", source_id="123", url="https://leboncoin.fr",
            title="PC Gamer RTX 4070 + Ryzen 5 5600 + 16Go", price=520,
            published_at="now", condition="Très bon état", city="Lille", zipcode="59000",
            search_name="Test",
        )
        score = ScoreResult(
            listing_uid="leboncoin:123", true_value=780.0, net_profit=248.0,
            bundle_details={}, reasons=(),
        )
        extra = [f"🟢 EASY · 0km de {settings.home_label} · logistique 10€ (retrait sur place)",
                 "RTX 4070: 450€ (marché) · Ryzen 5 5600: 100€ (estim)"]
        try:
            p.notifier.send_deal(fake, score, extra)
            print("Alerte de test envoyée sur Telegram — vérifie ton téléphone.")
        except Exception as e:
            print(f"Erreur d'envoi Telegram: {e}")

    elif cmd == "once":
        print(f"Cycle terminé: {Pipeline(settings).run_once()}")

    elif cmd == "loop":
        _pipeline_with_app(settings).run_forever()

    elif cmd == "serve":
        _serve(settings, int(sys.argv[2]) if len(sys.argv) > 2 else 8000)

    elif cmd == "bootstrap":
        pages = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        print(f"Warm-up terminé: {Pipeline(settings).bootstrap(pages)} annonces intégrées.")

    elif cmd == "top":
        _print_top(settings, int(sys.argv[2]) if len(sys.argv) > 2 else 10)

    elif cmd == "price":
        _price(settings, " ".join(sys.argv[2:]))

    elif cmd == "try":
        _try_search(settings, " ".join(sys.argv[2:]) or "rtx 4070")

    elif cmd == "stats":
        print(Store(settings.db_path).counts())

    else:
        print(__doc__)
        sys.exit(1)


def _pipeline_with_app(settings) -> Pipeline:
    """With APP_BACKEND=1 the scanner also pushes deals to subscribers and
    spends LLM time where subscribers actually live."""
    if os.environ.get("APP_BACKEND") != "1":
        return Pipeline(settings)
    from .api.accounts import Accounts
    from .api.fanout import PushFanout
    from .notify.push import ExpoPush

    api = load_api_settings()
    fanout = PushFanout(settings, api.deals_max_age_days, ExpoPush(api.expo_access_token))

    def origins():
        a = Accounts(settings.db_path)
        try:
            return [settings.home, *a.active_origins()]
        finally:
            a.close()

    return Pipeline(settings, fanout=fanout, origins=origins)


def _serve(settings, port: int):
    import uvicorn

    from .api.app import create_app

    api = load_api_settings()
    app = create_app(settings, api, dev_unlock_all=os.environ.get("DEV_UNLOCK_ALL") == "1")
    uvicorn.run(app, host=os.environ.get("API_HOST", "127.0.0.1"), port=port,
                proxy_headers=True, forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"))


def _print_top(settings, n: int):
    store = Store(settings.db_path)
    rows = store.conn.execute(
        "SELECT title, price, true_value, net_profit, zone, confidence, city, "
        "department, distance_km, url FROM listings "
        "WHERE net_profit IS NOT NULL ORDER BY net_profit DESC LIMIT ?",
        (n,),
    ).fetchall()
    if not rows:
        print("Aucune annonce valorisée encore — lance `bootstrap` puis `once`.")
        return
    for r in rows:
        loc = ", ".join(x for x in (r["city"], r["department"]) if x) or "?"
        dist = f"{r['distance_km']:.0f}km" if r["distance_km"] is not None else "?"
        print(f"\n[+{r['net_profit']:.0f}€ · {r['zone']} {dist}] {r['title'][:60]}")
        print(f"  {r['price']:.0f}€ -> valeur {r['true_value']:.0f}€ "
              f"(conf {r['confidence'] or 0:.0%}) · {loc}")
        print(f"  {r['url']}")


def _price(settings, query: str):
    if not query:
        print("Usage: price <query>  (ex: price rtx 4070)")
        return
    catalog = load_catalog(settings.pricebook_path)
    tracker = PriceTracker(Store(settings.db_path), catalog,
                           settings.min_comparables, settings.window_days)
    comps = extract_components(query, catalog)
    if not comps:
        print(f"Aucun composant reconnu dans: {query!r}")
        return
    for c in comps:
        q = tracker.price(c.key)
        print(f"{c.label:24s} {q.unit_value or 0:6.0f}€  [{q.source}, n={q.n}]")


def _try_search(settings, query: str):
    p = Pipeline(settings)
    source = p.sources.get("leboncoin")
    if source is None:
        print("Aucune source leboncoin configurée.")
        return
    url = f"https://www.leboncoin.fr/recherche?text={query.replace(' ', '+')}"
    search = SearchConfig(name="Try", url=url)
    print(f"Recherche: {query}")
    for l in source.fetch(search):
        _, comps = p._ingest(l)
        items = build_items(comps, None, p.catalog)
        appr = appraise(items, p.tracker, settings.realization_factor)
        dist = p.locator.distance_to_lille(l.zipcode)
        parts = ", ".join(c.label for c in comps) or "rien reconnu"
        print(f"  {l.price or 0:5.0f}€ | val {appr.true_value:5.0f}€ | "
              f"{f'{dist:.0f}km' if dist is not None else '?':>6} | {l.title[:45]}")
        if comps:
            print(f"        [{parts}]")


if __name__ == "__main__":
    main()
