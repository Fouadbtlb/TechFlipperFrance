"""Command line. Each command is one small function, listed in COMMANDS.

  python -m techflip.cli check              validate config, send a test Telegram alert
  python -m techflip.cli once               one scanning cycle (good first test)
  python -m techflip.cli loop               run the scanner forever (APP_BACKEND=1: + app pushes)
  python -m techflip.cli serve [port]       run the app API (default 8000)
  python -m techflip.cli health             is the scanner alive, what is in the database
  python -m techflip.cli bootstrap [pages]  one-shot market warm-up (default 3 pages)
  python -m techflip.cli top [n] [km]       best stored deals for the owner (within km of home)
  python -m techflip.cli price <query>      what the tracker thinks a part is worth
  python -m techflip.cli try <query>        value live listings for a query (no alert)

Shopping (the whole stored pool, ranked as things to buy):
  python -m techflip.cli web [port]         the shopping board in your browser (default 8765)
  python -m techflip.cli find <words> [--budget N] [--km N] [--cat X] [--live]
  python -m techflip.cli buy <budget> [cat] [--white] [--live]   best hardware for a budget
  python -m techflip.cli verify [n]         are the n best offers still online?
  python -m techflip.cli ingest <file.yaml> [pages]  refresh the pool, no alerts

Upkeep:
  python -m techflip.cli calibrate          pricebook seeds the market disagrees with
  python -m techflip.cli gaps               parts seen in ads that the pricebook misses
  python -m techflip.cli retrack            re-apply the teaching rule to stored ads
  python -m techflip.cli import <old.db>    bring listings, history, alerts and picks over
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

from .config import SearchConfig, Settings, load_api_settings, load_settings
from .domain import Listing, ScoreResult
from .pipeline import Pipeline, _make_source
from .pricing.appraise import appraise, build_items
from .pricing.catalog import load_catalog
from .pricing.extract import extract_components
from .pricing.identify import teaching_key
from .pricing.sold import load_sold
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
    limit, km = int(_arg(2, "10")), _arg(3)
    near = " AND distance_km <= ?" if km else ""
    rows = Store(settings.db_path).conn.execute(
        "SELECT title, price, true_value, net_profit, zone, confidence, city, distance_km, url "
        f"FROM listings WHERE net_profit IS NOT NULL AND status='active'{near} "
        "ORDER BY net_profit DESC LIMIT ?", (*([float(km)] if km else []), limit)).fetchall()
    where = f" à moins de {float(km):.0f} km de {settings.home_label}" if km else ""
    if not rows:
        print(f"Aucune annonce valorisée{where} : lance `bootstrap` puis `once`.")
    elif km:
        print(f"Meilleures affaires{where} :")
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
    tracker = PriceTracker(Store(settings.db_path), catalog, settings.min_comparables, settings.window_days,
                           owner_sales=load_sold(settings.sold_path))
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
        appr = appraise(build_items(comps, None, p.catalog, f"{l.title} {l.description}", l.title),
                        p.tracker, settings.realization_factor, l.uid)
        dist = p.locator.distance(l.zipcode, l.lat, l.lng)
        where = f"{dist:.0f}km" if dist is not None else "?"
        print(f"  {l.price or 0:5.0f}€ | val {appr.true_value:5.0f}€ | {where:>6} | {l.title[:45]}")
        if comps:
            print(f"        [{', '.join(c.label for c in comps)}]")


# ---------------------------------------------------------------- shopping

def _opts(args: list[str], *names: str) -> tuple[dict, list[str]]:
    """`--name value` pairs and `--flag`s out of args, and the remaining words."""
    found, words, i = {}, [], 0
    while i < len(args):
        a = args[i]
        if a.startswith("--") and a[2:] in names and i + 1 < len(args) and not args[i + 1].startswith("--"):
            found[a[2:]] = args[i + 1]
            i += 2
        elif a.startswith("--"):
            found[a[2:]] = True
            i += 1
        else:
            words.append(a)
            i += 1
    return found, words


def _print_finds(finds, n: int = 15) -> None:
    for f in finds[:n]:
        d = f"{f.distance:.0f}km" if f.distance is not None else "?km"
        warn = f" [{', '.join(f.flags)}]" if f.flags else ""
        print(f"{f.price:6.0f}€  vaut ~{f.value:5.0f}€  {f.savings:+6.0f}€ net  {d:>6} "
              f"{(f.city or '?')[:14]:<14} {f.title[:50]}{warn}")
        print(f"        {f.url}")


def cmd_web(settings: Settings) -> None:
    from .web import serve
    serve(settings, port=int(_arg(2, "8765")))


def cmd_find(settings: Settings) -> None:
    from .hunt import filter_finds, rank, sweep
    from .web import Board

    opts, words = _opts(sys.argv[2:], "budget", "km", "cat")
    query = " ".join(words)
    budget = float(opts["budget"]) if "budget" in opts else None
    if opts.get("live") and query:
        stats = sweep(Pipeline(settings), [query], max_price=budget, category=opts.get("cat"))
        print(f"Recherche en direct : {query!r}  {stats}")
    board = Board(settings)
    sel = rank(filter_finds(board.finds, query=query or None, budget=budget,
                            max_km=float(opts["km"]) if "km" in opts else None, category=opts.get("cat")))
    print(f"\n{len(sel)} offre(s) sur {len(board.finds)} chiffrées (gain net, trajet déduit)\n")
    _print_finds(sel)


def cmd_buy(settings: Settings) -> None:
    """Best hardware you can get for a budget, then the same just above it."""
    from .hunt import BROAD_TERMS, filter_finds, rank, sweep
    from .web import Board

    opts, words = _opts(sys.argv[2:])
    if not words:
        sys.exit("Usage : buy <budget> [catégorie] [--white] [--live]   (ex : buy 280 gpu --white)")
    budget, category = float(words[0]), (words[1] if len(words) > 1 else "gpu")
    if opts.get("live"):
        terms = BROAD_TERMS.get(category, (category,))
        print(f"Recherche en direct : {sweep(Pipeline(settings), terms, max_price=budget * 1.35, category=category)}")
    finds = filter_finds(Board(settings).finds, category=category, budget=budget * 1.35,
                         white_only=bool(opts.get("white")))
    honest = [f for f in rank(finds, "value") if not f.is_bait]
    print(f"\n{category} dans {budget:.0f}€, du meilleur matériel au moins bon :\n")
    _print_finds([f for f in honest if f.price <= budget], 10)
    over = [f for f in honest if f.price > budget][:3]
    if over:
        print("\n--- juste au-dessus du budget (à négocier) ---")
        _print_finds(over, 3)


def cmd_verify(settings: Settings) -> None:
    """Re-check the best offers. Three answers, never two: "non vérifiée" is
    not "en ligne" (a blocked site answers nothing)."""
    from . import liveness
    from .hunt import filter_finds, rank
    from .web import Board

    board = Board(settings)
    top = rank(filter_finds(board.finds, max_km=120, min_confidence=0.5, min_savings=1))[:int(_arg(2, "20"))]
    print(f"Vérification des {len(top)} meilleures offres (1 requête chacune)…\n")
    sources = {name: _make_source(name, settings) for name in {f.source for f in top}}
    results = liveness.verify(board.store, sources, [f.uid for f in top])["results"]
    tags = {"alive": "EN LIGNE   ", "gone": "PARTIE     ", "unknown": "NON VÉRIFIÉE"}
    for f in top:
        verdict = results.get(f.uid, "unknown")
        print(f"{tags[verdict]}  {f.price:6.0f}€ {f.savings:+5.0f}€  {f.distance:5.0f}km  {f.title[:42]}")
        if verdict != "gone":
            print(f"               {f.url}")


def cmd_ingest(settings: Settings) -> None:
    from .ingest import ingest

    path = _arg(2, "config/searches.yaml")
    cfg = load_settings(path)
    sources = {name: _make_source(name, cfg) for name in {s.source for s in cfg.searches}}
    stats = ingest(Store(cfg.db_path), cfg.searches, sources, catalog=load_catalog(cfg.pricebook_path),
                   max_pages=int(_arg(3, "4")))
    print(f"{path}: {stats}")


# ---------------------------------------------------------------- upkeep

def cmd_calibrate(settings: Settings) -> None:
    tracker = PriceTracker(Store(settings.db_path), load_catalog(settings.pricebook_path),
                           settings.min_comparables, settings.window_days)
    rows = tracker.drifted_seeds()
    if not rows:
        print("Aucun prix de départ à corriger : le marché confirme le pricebook.")
        return
    print(f"{len(rows)} prix de départ en désaccord avec le marché :\n")
    for r in rows:
        print(f"  {r['label']:22s} départ {r['seed']:6.0f} -> marché {r['market']:6.0f} ({r['drift']:+.0%}, n={r['n']})")
    print("\nÀ reporter dans config/pricebook.yaml :")
    for r in rows:
        print(f"  {r['key']}: seed: {r['market']:.0f}")


def cmd_gaps(settings: Settings) -> None:
    from .hunt import gaps

    rows = gaps(Store(settings.db_path), load_catalog(settings.pricebook_path))
    if not rows:
        print("Aucun angle mort : toutes les pièces citées sont au catalogue.")
        return
    desktop = [r for r in rows if not r["mobile"]]
    mobile = [r for r in rows if r["mobile"]]
    print(f"{len(desktop)} pièce(s) absentes du pricebook (chaque occurrence = une machine sous-évaluée) :\n")
    for r in desktop:
        print(f"  {r['n']:4d}x  {r['kind']:3s}  {r['token']:<18s} ex : {r['example']}")
    if mobile:
        print(f"\n{len(mobile)} puce(s) de portable, volontairement non ajoutées : "
              + ", ".join(r["token"] for r in mobile))
    print("\nAjoute les lignes utiles dans config/pricebook.yaml, puis : retrack")


def cmd_retrack(settings: Settings) -> None:
    catalog = load_catalog(settings.pricebook_path)
    print(f"Règles réappliquées : {Store(settings.db_path).retrack(lambda l: teaching_key(l, catalog))}")


def cmd_import(settings: Settings) -> None:
    old = _arg(2)
    if not old or not os.path.exists(old):
        sys.exit("Usage : import <ancienne-base.db>")
    store = Store(settings.db_path)
    print(f"Importé : {store.import_from(old)}")
    cmd_retrack(settings)


COMMANDS = {
    "check": cmd_check, "once": cmd_once, "loop": cmd_loop, "serve": cmd_serve, "health": cmd_health,
    "bootstrap": cmd_bootstrap, "top": cmd_top, "price": cmd_price, "try": cmd_try,
    "web": cmd_web, "find": cmd_find, "buy": cmd_buy, "verify": cmd_verify, "ingest": cmd_ingest,
    "calibrate": cmd_calibrate, "gaps": cmd_gaps, "retrack": cmd_retrack, "import": cmd_import,
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
