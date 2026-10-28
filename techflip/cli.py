"""Command line. Each command is one small function, listed in COMMANDS.

  python -m techflip.cli check              validate config, send a test Telegram alert
  python -m techflip.cli once               one scanning cycle (good first test)
  python -m techflip.cli loop               run the scanner forever (APP_BACKEND=1: + app pushes)
  python -m techflip.cli serve [port]       run the app API (default 8000)
  python -m techflip.cli health             is the scanner alive, what is in the database
  python -m techflip.cli bootstrap [pages]  one-shot market warm-up (default 3 pages)
  python -m techflip.cli top [n]            best stored deals for the owner
  python -m techflip.cli price <query>      what the tracker thinks a part is worth
  python -m techflip.cli try <query>        value live listings for a query (no alert)
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

from .config import SearchConfig, Settings, load_api_settings, load_settings
from .domain import Listing, ScoreResult
from .pipeline import Pipeline
from .pricing.appraise import appraise, build_items
from .pricing.catalog import load_catalog
from .pricing.extract import extract_components
from .pricing.tracker import PriceTracker
from .storage import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _arg(i: int, default: str = "") -> str:
    return sys.argv[i] if len(sys.argv) > i else default


def _require_searches(settings: Settings) -> None:
    if not settings.searches:
        sys.exit("Aucune recherche dans config/searches.yaml : ajoute au moins une URL Leboncoin.")


# ---------------------------------------------------------------- commands

def cmd_check(settings: Settings) -> None:
    _require_searches(settings)
    for s in settings.searches:
        print(f"  - [{s.kind}] {s.name}")
    p = Pipeline(settings)
    fake = Listing(source="leboncoin", source_id="123", url="https://leboncoin.fr",
                   title="PC Gamer RTX 4070 + Ryzen 5 5600 + 16Go", price=520, published_at="now",
                   condition="Très bon état", city=settings.home_label, search_name="Test")
    score = ScoreResult(listing_uid=fake.uid, true_value=780.0, net_profit=248.0, bundle_details={})
    p.notifier.send_deal(fake, score, [f"🟢 EASY · 0km de {settings.home_label} · logistique 10€",
                                       "RTX 4070: 450€ (marché) · Ryzen 5 5600: 100€ (estim)"])
    print("Alerte de test envoyée (si Telegram est configuré).")


def cmd_once(settings: Settings) -> None:
    _require_searches(settings)
    print(f"Cycle terminé : {Pipeline(settings).run_once()}")


def cmd_loop(settings: Settings) -> None:
    _require_searches(settings)
    _pipeline_with_app(settings).run_forever()


def cmd_serve(settings: Settings) -> None:
    import uvicorn

    from .api.app import create_app

    app = create_app(settings, load_api_settings(), dev_unlock_all=os.environ.get("DEV_UNLOCK_ALL") == "1")
    uvicorn.run(app, host=os.environ.get("API_HOST", "127.0.0.1"), port=int(_arg(2, "8000")),
                proxy_headers=True, forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"))


def cmd_health(settings: Settings) -> None:
    store = Store(settings.db_path)
    beat = store.get_meta("scanner")
    if beat is None:
        print("Scanner : aucun cycle enregistré pour l’instant.")
    else:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(beat.pop("updated_at"))
        print(f"Scanner : dernier cycle il y a {int(age.total_seconds() // 60)} min, {beat}")
    pruned = store.get_meta("pruned")
    if pruned:
        print(f"Purge : {pruned}")
    print(f"Base : {store.counts()}")


def cmd_bootstrap(settings: Settings) -> None:
    _require_searches(settings)
    print(f"Préchauffage terminé : {Pipeline(settings).bootstrap(int(_arg(2, '3')))} annonces intégrées.")


def cmd_top(settings: Settings) -> None:
    rows = Store(settings.db_path).conn.execute(
        "SELECT title, price, true_value, net_profit, zone, confidence, city, distance_km, url "
        "FROM listings WHERE net_profit IS NOT NULL AND status='active' "
        "ORDER BY net_profit DESC LIMIT ?", (int(_arg(2, "10")),)).fetchall()
    if not rows:
        print("Aucune annonce valorisée encore : lance `bootstrap` puis `once`.")
    for r in rows:
        dist = f"{r['distance_km']:.0f}km" if r["distance_km"] is not None else "?"
        print(f"\n[+{r['net_profit']:.0f}€ · {r['zone']} {dist}] {r['title'][:60]}")
        print(f"  {r['price']:.0f}€ -> valeur {r['true_value']:.0f}€ (conf {r['confidence'] or 0:.0%}) · {r['city'] or '?'}")
        print(f"  {r['url']}")


def cmd_price(settings: Settings) -> None:
    query = " ".join(sys.argv[2:])
    if not query:
        sys.exit("Usage : price <requête>  (ex : price rtx 4070)")
    catalog = load_catalog(settings.pricebook_path)
    tracker = PriceTracker(Store(settings.db_path), catalog, settings.min_comparables, settings.window_days)
    comps = extract_components(query, catalog)
    if not comps:
        print(f"Aucun composant reconnu dans : {query!r}")
    for c in comps:
        q = tracker.price(c.key)
        print(f"{c.label:24s} {q.unit_value or 0:6.0f}€  [{q.source}, n={q.n}, bas={q.low}, jours={q.days_to_sell}]")


def cmd_try(settings: Settings) -> None:
    query = " ".join(sys.argv[2:]) or "rtx 4070"
    p = Pipeline(settings)
    source = p.sources.get("leboncoin")
    if source is None:
        sys.exit("Aucune source leboncoin configurée.")
    search = SearchConfig(name="Try", url=f"https://www.leboncoin.fr/recherche?text={query.replace(' ', '+')}")
    print(f"Recherche : {query}")
    for l in source.fetch(search):
        _, comps = p._ingest(l)
        appr = appraise(build_items(comps, None, p.catalog), p.tracker, settings.realization_factor, l.uid)
        dist = p.locator.distance(l.zipcode, l.lat, l.lng)
        where = f"{dist:.0f}km" if dist is not None else "?"
        print(f"  {l.price or 0:5.0f}€ | val {appr.true_value:5.0f}€ | {where:>6} | {l.title[:45]}")
        if comps:
            print(f"        [{', '.join(c.label for c in comps)}]")


COMMANDS = {
    "check": cmd_check, "once": cmd_once, "loop": cmd_loop, "serve": cmd_serve, "health": cmd_health,
    "bootstrap": cmd_bootstrap, "top": cmd_top, "price": cmd_price, "try": cmd_try,
}


def _pipeline_with_app(settings: Settings) -> Pipeline:
    """With APP_BACKEND=1 the scanner also pushes deals to subscribers and
    spends vision-model time where subscribers actually live."""
    if os.environ.get("APP_BACKEND") != "1":
        return Pipeline(settings)
    from .api.accounts import Accounts
    from .api.fanout import PushFanout
    from .notify.push import ExpoPush

    api = load_api_settings()

    def origins():
        accounts = Accounts(settings.db_path)
        try:
            return [settings.home, *accounts.active_origins()]
        finally:
            accounts.close()

    fanout = PushFanout(settings, api.deals_max_age_days, ExpoPush(api.expo_access_token))
    return Pipeline(settings, fanout=fanout, origins=origins)


def main() -> None:
    command = COMMANDS.get(_arg(1, "loop"))
    if command is None:
        sys.exit(__doc__)
    command(load_settings())


if __name__ == "__main__":
    main()
