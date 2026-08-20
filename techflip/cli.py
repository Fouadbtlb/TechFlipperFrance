"""CLI.

  python -m techflip.cli check              validate config, ping Telegram
  python -m techflip.cli once               one polling cycle (good first test)
  python -m techflip.cli loop               run forever (the real thing)
  python -m techflip.cli bootstrap [pages]  one-shot market warm-up (default 3)
  python -m techflip.cli top [n]            best stored deals, in the terminal
  python -m techflip.cli price <query>      what the tracker thinks a part is worth
  python -m techflip.cli try <query>        value live listings for a query (no alert)
  python -m techflip.cli buy <budget> [cat] [--white]
                                           best part you can buy for that budget
  python -m techflip.cli web [port]         browse every offer in a browser
  python -m techflip.cli find <query> [--budget N] [--km N] [--live]
                                           shopping search over the whole pool
  python -m techflip.cli calibrate          seeds the scraped market disagrees with
  python -m techflip.cli retrack            re-apply recognition rules to stored ads
  python -m techflip.cli stats              DB counters
"""
from __future__ import annotations

import json
import logging
import sys

from .buying import find_buys, rank_buys
from .config import SearchConfig, load_settings
from .domain import Listing, ScoreResult
from .pipeline import Pipeline, recompute_primary_components
from .pricing.appraise import appraise, build_items
from .pricing.catalog import load_catalog
from .pricing.sold import load_sold
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
        extra = ["🟢 EASY · 0km de Lille · logistique 10€ (retrait sur place)",
                 "RTX 4070: 450€ (marché) · Ryzen 5 5600: 100€ (estim)"]
        try:
            p.notifier.send_deal(fake, score, extra)
            print("Alerte de test envoyée sur Telegram — vérifie ton téléphone.")
        except Exception as e:
            print(f"Erreur d'envoi Telegram: {e}")

    elif cmd == "once":
        print(f"Cycle terminé: {Pipeline(settings).run_once()}")

    elif cmd == "loop":
        Pipeline(settings).run_forever()

    elif cmd == "bootstrap":
        pages = int(sys.argv[2]) if len(sys.argv) > 2 else 3
        print(f"Warm-up terminé: {Pipeline(settings).bootstrap(pages)} annonces intégrées.")

    elif cmd == "top":
        _print_top(settings, int(sys.argv[2]) if len(sys.argv) > 2 else 10)

    elif cmd == "price":
        _price(settings, " ".join(sys.argv[2:]))

    elif cmd == "try":
        _try_search(settings, " ".join(sys.argv[2:]) or "rtx 4070")

    elif cmd == "buy":
        _buy(settings, sys.argv[2:])

    elif cmd == "web":
        from .web import serve
        serve(settings, port=int(sys.argv[2]) if len(sys.argv) > 2 else 8765)

    elif cmd == "find":
        _find(settings, sys.argv[2:])

    elif cmd == "gaps":
        _gaps(settings)

    elif cmd == "verify":
        _verify(settings, int(sys.argv[2]) if len(sys.argv) > 2 else 20)

    elif cmd == "calibrate":
        _calibrate(settings)

    elif cmd == "retrack":
        p = Pipeline(settings)
        print(f"Re-application des regles de reconnaissance: "
              f"{recompute_primary_components(p.store, p.catalog)}")

    elif cmd == "stats":
        print(Store(settings.db_path).counts())

    else:
        print(__doc__)
        sys.exit(1)


def _verify(settings, n: int):
    """Re-search the best offers to see which are still actually for sale.

    One request per listing, so it checks the top n only. The ad page cannot
    answer this: Leboncoin returns 410 with an identical body for live and dead
    ads alike (measured 2026-08-18).
    """
    from .geo import Locator
    from .hunt import filter_finds, rank, scan
    from .liveness import verify

    p = Pipeline(settings)
    finds = scan(p.store, p.catalog, p.tracker, Locator(),
                 easy_km=settings.easy_km, medium_km=settings.medium_km,
                 realization=settings.realization_factor)
    top = rank(filter_finds(finds, max_km=120, min_confidence=0.5, min_savings=1),
               "savings")[:n]
    print(f"Verification des {len(top)} meilleures offres (1 requete chacune)...\n")
    stats = verify(p.store, p.sources, [f.uid for f in top])
    results = stats.pop("results")
    print(f"{stats}\n")

    # Three states, never two. "non verifiee" is not "en ligne": a blocked
    # source skips every one of its listings, and printing those as confirmed
    # is how the board came to hand out dead links.
    tags = {"alive": "CONFIRMEE  ", "gone": "DISPARUE   ", "skipped": "NON VERIFIE"}
    for f in top:
        verdict = results.get(f.uid, "skipped")
        print(f"{tags[verdict]}  {f.price:6.0f}€ +{f.savings:4.0f}  "
              f"{f.distance:5.0f}km  {f.title[:42]}")
        if verdict != "gone":
            print(f"               {f.url}")
    n_skip = stats["skipped"]
    if n_skip:
        print(f"\n{n_skip} non verifiee(s): source bloquee ou titre trop vague. "
              f"Relance plus tard, ne les crois pas sur parole.")


def _gaps(settings):
    """What the catalog is blind to, ranked by how often it costs us."""
    from .hunt import gaps

    catalog = load_catalog(settings.pricebook_path)
    rows = gaps(Store(settings.db_path), catalog)
    if not rows:
        print("Aucun angle mort: toutes les pieces citees sont au catalogue.")
        return
    desktop = [r for r in rows if not r["mobile"]]
    mobile = [r for r in rows if r["mobile"]]
    print(f"{len(desktop)} piece(s) desktop absentes du pricebook "
          f"(chaque occurrence = une machine sous-evaluee):\n")
    for r in desktop:
        print(f"  {r['n']:4d}x  {r['kind']:3s}  {r['token']:<18s} ex: {r['example']}")
    if mobile:
        print(f"\n{len(mobile)} puce(s) mobiles vues, volontairement NON ajoutees "
              f"(prix portable != prix desktop):")
        print("  " + ", ".join(r["token"] for r in mobile))
    print("\nAjoute les lignes utiles dans config/pricebook.yaml, puis: retrack")


def _find(settings, args: list[str]):
    """Shopping search: the whole pool, no date filter, no alert bookkeeping."""
    from .geo import Locator
    from .hunt import filter_finds, rank, scan, sweep

    def opt(name, cast=float):
        if name in args:
            i = args.index(name)
            if i + 1 < len(args):
                return cast(args[i + 1])
        return None

    live = "--live" in args
    budget, km = opt("--budget"), opt("--km")
    cat = opt("--cat", str)
    words = [a for a in args if not a.startswith("--")]
    skip = {str(v) for v in (budget, km, cat) if v is not None}
    skip |= {str(int(v)) for v in (budget, km) if v is not None}
    query = " ".join(w for w in words if w not in skip)

    p = Pipeline(settings)
    if live and query:
        print(f"Recherche en direct: {query!r} ...")
        print(f"  {sweep(p, [query], max_price=budget, category=cat)}")

    finds = scan(p.store, p.catalog, p.tracker, Locator(),
                 easy_km=settings.easy_km, medium_km=settings.medium_km,
                 realization=settings.realization_factor)
    sel = rank(filter_finds(finds, query=query or None, budget=budget,
                            max_km=km, category=cat), "savings")
    print(f"\n{len(sel)} offre(s) sur {len(finds)} chiffrees\n")
    for f in sel[:15]:
        d = f"{f.distance:.0f}km" if f.distance is not None else "?km"
        warn = (" [" + ", ".join(f.flags) + "]") if f.flags else ""
        print(f"{f.price:6.0f}€  vaut ~{f.value:5.0f}€  {f.savings:+6.0f}€  "
              f"{d:>7} {f.city or '?':<16} {f.title[:52]}{warn}")
        print(f"        {f.url}")


def _calibrate(settings):
    catalog = load_catalog(settings.pricebook_path)
    tracker = PriceTracker(Store(settings.db_path), catalog,
                           settings.min_comparables, settings.window_days,
                           sold=load_sold(settings.sold_path))
    rows = tracker.drifted_seeds()
    if not rows:
        print("Aucun seed a corriger: le marche confirme le pricebook.")
        return
    print(f"{len(rows)} seed(s) en desaccord avec le marche scrape:\n")
    for r in rows:
        print(f"  {r['label']:22s} seed {r['seed']:6.0f} -> marche {r['market']:6.0f} "
              f"({r['drift']:+.0%}, n={r['n']})")
    print("\nA reporter dans config/pricebook.yaml:")
    for r in rows:
        print(f"  {r['key']}: seed: {r['market']:.0f}")


def _buy(settings, args: list[str]):
    if not args:
        print("Usage: buy <budget> [categorie] [--white]   (ex: buy 280 gpu --white)")
        return
    white_only = "--white" in args
    args = [a for a in args if a != "--white"]
    try:
        budget = float(args[0])
    except ValueError:
        print(f"Budget invalide: {args[0]!r}")
        return
    category = args[1] if len(args) > 1 else "gpu"

    p = Pipeline(settings)
    buys = find_buys(p, category, budget, stretch=1.35)
    picks = rank_buys(buys, budget, white_only)
    tag = " blanc(he)s" if white_only else ""
    print(f"\n{len(buys)} annonce(s) {category} vues · {len(picks)}{tag} dans {budget:.0f}€\n")
    for b in picks[:10]:
        d = f"{b.distance:.0f}km" if b.distance is not None else "?km"
        deal = f"  (-{b.discount:.0f}€ sous marché)" if b.discount > 0 else ""
        w = " · BLANCHE" if b.white else ""
        print(f"{b.label:20s} {b.price:6.0f}€  vaut ~{b.value:.0f}€{deal}")
        print(f"  {b.zone} · {d} · {b.city or '?'}{w}")
        print(f"  {b.title[:70]}")
        if b.sales_copy:
            print("  ⚠️  texte copié de la fiche produit — exige une vraie photo")
        print(f"  {b.url}\n")

    over = sorted((b for b in buys if b.price > budget and b.price >= 0.45 * b.value
                   and (b.white or not white_only)),
                  key=lambda b: (-b.value, b.price))[:3]
    if over:
        print(f"--- juste au-dessus du budget (à négocier) ---")
        for b in over:
            d = f"{b.distance:.0f}km" if b.distance is not None else "?km"
            w = " · BLANCHE" if b.white else ""
            warn = "  ⚠️ texte fiche produit" if b.sales_copy else ""
            print(f"{b.label:20s} {b.price:6.0f}€  vaut ~{b.value:.0f}€ · {b.zone} · {d}{w}{warn}")
            print(f"  {b.url}")


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
                           settings.min_comparables, settings.window_days,
                           sold=load_sold(settings.sold_path))
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
