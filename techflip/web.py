"""Local web board: every offer worth a look, on one page, for a human to sort.

Telegram is a firehose with one bit of state (sent / not sent) and no way to say
"keep this one, I'll go Saturday". The whole pool is also far larger than the
handful of ads that ever cleared the alert bar, and most of what is genuinely
worth buying never clears it: it is simply a fair price on a thing you want.

So this serves the stored pool as a shopping board, filterable by budget,
category, distance and text, with a shortlist you own. No framework and no
build step: one stdlib HTTP server and one file (the map loads Leaflet from a
CDN), because a tool you have to deploy is a tool you stop running.

It listens on 127.0.0.1 only, and refuses requests whose Host is not local
(DNS rebinding) and writes that do not come from its own page: any website
open in the same browser could otherwise start a scraping sweep from your IP.
"""
from __future__ import annotations

import html
import json
import logging
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .geo import Locator
from .hunt import SORTS, categories, filter_finds, rank, scan, sweep
from .pricing.catalog import load_catalog
from .pricing.sold import load_sold
from .pricing.tracker import PriceTracker
from .storage import Store
from .tuning import SHOP_SOURCES

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
SOURCE_NAME = {"leboncoin": "Leboncoin", "2ememain": "2ememain",
               "cashconverters": "Cash Converters", "cashexpress": "Cash Express"}

log = logging.getLogger(__name__)

CAT_LABEL = {"pc": "PC complet", "console": "Consoles", "gpu": "Cartes graphiques",
             "cpu": "Processeurs", "ram": "Mémoire", "storage": "Stockage",
             "psu": "Alimentations", "motherboard": "Cartes mères", "phone": "Téléphones",
             "tablet": "Tablettes", "laptop": "Portables", "monitor": "Écrans",
             "controller": "Manettes", "game": "Jeux", "cooler": "Refroidissement",
             "case": "Boîtiers"}

# flag -> (pill, tooltip, tone). Tones follow the app: oxblood is caution,
# amber is "look closely", green is money, ink is information.
FLAG_LABEL = {
    "bait": ("Arnaque probable", "Prix trop bas pour être vrai : annonce bidon, photo volée "
             "ou paiement par virement.", "risk"),
    "broken": ("En panne", "L’annonce parle de panne ou de casse. Valeur déjà réduite.", "warn"),
    "locked": ("Bloqué opérateur", "Utilisable chez un seul opérateur : revente plus lente "
               "et moins chère.", "warn"),
    "laptop": ("Portable", "Chiffré avec des prix de pièces de bureau. Une puce de portable "
               "vaut nettement moins.", "warn"),
    "sales_copy": ("Texte de fiche produit", "Description copiée du site du fabricant, pas "
                   "écrite par un vendeur. Exige une vraie photo.", "warn"),
    "cut": ("Prix baissé", "Le vendeur a déjà baissé son prix : il peut rebaisser.", "profit"),
    "sitting": ("Ne part pas", "Toujours en ligne des semaines après sa parution : le marché "
                "a refusé ce prix. Négocie.", "info"),
    "partial": ("Pièces non chiffrées", "Une pièce citée n’est pas au catalogue : la valeur "
                "affichée est un plancher.", "muted"),
    "stale": ("Ancienne", "Pas revue depuis plus de 10 jours : probablement vendue.", "muted"),
}
SHOP_PILL = ("Magasin", "Vendu par une enseigne : prix ferme, pas de négociation.", "info")

ZONE_CLASS = {"EASY": "z-easy", "MEDIUM": "z-med", "HARD": "z-hard"}


class Board:
    """Holds the scan, so a page load is a filter over memory, not a rescan."""

    def __init__(self, settings):
        self.settings = settings
        self.store = Store(settings.db_path)
        self.catalog = load_catalog(settings.pricebook_path)
        # Ads still online weeks later did not sell at that price, so they are
        # left out of the board's medians (STALE_DAYS).
        self.tracker = PriceTracker(self.store, self.catalog,
                                    settings.min_comparables, settings.window_days,
                                    owner_sales=load_sold(settings.sold_path),
                                    stale_days=settings.stale_days)
        self.locator = Locator(origin=settings.home)
        self._lock = threading.Lock()
        self.finds = []
        self.busy = ""
        self.refresh()

    def refresh(self):
        with self._lock:
            self.finds = scan(self.store, self.catalog, self.tracker, self.locator,
                              easy_km=self.settings.easy_km,
                              medium_km=self.settings.medium_km,
                              realization=self.settings.realization_factor,
                              cost_per_km=self.settings.cost_per_km)
        return len(self.finds)

    def go_look(self, terms, max_price=None, category=None):
        """Run a live search then rescan. Long, so the UI polls `busy`."""
        from .pipeline import Pipeline
        self.busy = "Recherche en cours : " + ", ".join(terms)
        try:
            pipeline = Pipeline(self.settings)
            stats = sweep(pipeline, terms, max_price=max_price, category=category)
            n = self.refresh()
            self.busy = ""
            log.info("sweep %s -> %s, %d offres", terms, stats, n)
        except Exception:
            self.busy = ""
            log.exception("sweep failed")


# ---------- rendering ----------


def _e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _euros(x: float, sign: bool = False) -> str:
    s = f"{abs(x):,.0f}".replace(",", " ") + " €"
    if not sign:
        return s
    return ("+" if x > 0 else "−" if x < 0 else "") + s


def _pill(label: str, tip: str, tone: str) -> str:
    return f"<span class='pill t-{tone}' title='{_e(tip)}'>{_e(label)}</span>"


def _card(f, pick) -> str:
    state = pick["state"] if pick else ""
    note = (pick["note"] if pick else "") or ""
    good = f.savings > 0 and not f.is_bait
    where = f"{f.distance:.0f} km" if f.distance is not None else "distance inconnue"
    seen = (f"vue il y a {f.age_days:.0f} j" if f.age_days and f.age_days >= 1
            else "vue aujourd’hui")
    pills = ([_pill(*SHOP_PILL)] if f.source in SHOP_SOURCES else []) + [
        _pill(*FLAG_LABEL[k]) for k in f.flags if k in FLAG_LABEL]
    img = (f"<img loading='lazy' referrerpolicy='no-referrer' src='{_e(f.image)}' alt='' "
           f"onerror='this.remove()'>" if f.image else "")
    was = (f"<s class='was'>{_euros(f.price_cut['first'])}</s> " if f.price_cut else "")
    ledger = [("Revente estimée", _euros(f.value), ""), ("Prix demandé", "− " + _euros(f.price), "")]
    if f.trip:
        ledger.append(("Trajet ou envoi", "− " + _euros(f.trip), ""))
    rows = "".join(f"<div class='lrow'><span>{_e(a)}</span><span>{_e(b)}</span></div>" for a, b, _ in ledger)
    parts = "".join(f"<li>{_e(line)}</li>" for line in f.lines)
    lev = f"<p class='lev'>{_e(f.leverage)}</p>" if f.leverage else ""
    kept = state == "interested"

    return f"""
<article class="card{' is-hidden' if state == 'hidden' else ''}{' is-kept' if kept else ''}" data-uid="{_e(f.uid)}">
  <a class="thumb" href="{_e(f.url)}" target="_blank" rel="noopener noreferrer">{img}</a>
  <div class="body">
    <div class="head">
      <div class="what">
        <h3><a href="{_e(f.url)}" target="_blank" rel="noopener noreferrer">{_e(f.title)}</a></h3>
        <p class="meta">{was}<b>{_euros(f.price)}</b> · <span class="dot {ZONE_CLASS.get(f.zone, '')}"></span>{_e(where)}
          · {_e(f.city or '?')} · {_e(SOURCE_NAME.get(f.source, f.source))}</p>
      </div>
      <div class="net {'up' if good else 'down'}"><span>{_euros(f.savings, sign=True)}</span><small>{_e(seen)}</small></div>
    </div>
    {f'<div class="pills">{"".join(pills)}</div>' if pills else ''}{lev}
    <details><summary>Le calcul <span>· {f.n_priced} pièce{'s' if f.n_priced > 1 else ''}, confiance {f.confidence:.0%}</span></summary>
      <div class="ledger">{rows}<div class="lrow total"><span>Ce qu’il te reste</span><span>{_euros(f.savings, sign=True)}</span></div></div>
      <ul class="parts">{parts}</ul>
    </details>
    <div class="actions">
      <button class="keep" onclick="pick(this,'interested')">{'Gardée' if kept else 'Garder'}</button>
      <button class="hide" onclick="pick(this,'hidden')">Masquer</button>
      <input class="note" placeholder="Une note (samedi, à négocier…)" value="{_e(note)}" onchange="pick(this,'interested',this.value)">
    </div>
  </div>
</article>"""


def _page(board, q) -> str:
    picks = board.store.picks()
    show = q.get("show", "open")
    finds = board.finds
    if show == "interested":
        finds = [f for f in finds if _state(picks, f.uid) == "interested"]
    elif show == "open":
        finds = [f for f in finds if _state(picks, f.uid) != "hidden"]

    # A first visit with no query string gets a usable board rather than the
    # raw pool: the unfiltered "best deal" list was topped by a Steam Deck 902km
    # away and valued off seeds. Both defaults are rendered into the form, so
    # they are visible and one click from being cleared.
    ulat, ulng, urad = _num(q.get("ulat")), _num(q.get("ulng")), _num(q.get("urad"))
    first_visit = not any(q.get(k) for k in ("q", "budget", "cat", "km", "age", "sort", "show",
                                             "conf", "nohs", "ulat", "ulng", "urad"))
    km = _num(q.get("km")) if not first_visit else 120.0
    circle = None not in (ulat, ulng, urad)
    if circle:
        km = None
    conf = _num(q.get("conf")) if not first_visit else 0.5

    sort = q.get("sort") if q.get("sort") in SORTS else "savings"
    sel = rank(filter_finds(
        finds, budget=_num(q.get("budget")), category=q.get("cat") or None, max_km=km,
        min_savings=_num(q.get("min")), kind=q.get("kind") or None, query=q.get("q") or None,
        max_age_days=_num(q.get("age")), hide_broken=q.get("nohs") == "1", min_confidence=conf,
        ulat=ulat, ulng=ulng, urad=urad,
    ), sort)
    shown = sel[:400]

    def opts(pairs, current):
        return "".join(f"<option value='{_e(v)}'{' selected' if current == v else ''}>{_e(t)}</option>"
                       for v, t in pairs)

    def show_link(key, label):
        params = {**q, "show": key}
        href = "?" + urllib.parse.urlencode(params)
        return f"<a class='seg{' on' if show == key else ''}' href='{_e(href)}'>{_e(label)}</a>"

    kept = sum(1 for p in picks.values() if p["state"] == "interested")
    best = max((f.savings for f in shown if not f.is_bait), default=None)
    markers = [{"lat": f.lat, "lng": f.lng, "title": _e(f.title), "url": _e(f.url),
                "price": _euros(f.price), "net": round(f.savings), "zone": f.zone,
                "city": _e(f.city or "?")}
               for f in shown if f.lat is not None and f.lng is not None]
    hidden_circle = (f'<input type="hidden" name="ulat" value="{ulat}"><input type="hidden" name="ulng" '
                     f'value="{ulng}"><input type="hidden" name="urad" value="{urad}">') if circle else ""
    clear_circle = (f'<button type="button" class="ghost" onclick="clearCircle()">'
                    f'Zone de {urad:g} km &times;</button>') if circle else ""

    return _SHELL.format(
        css=_CSS, js=_JS,
        home_label=_e(board.settings.home_label),
        n_shown=len(sel), n_total=len(board.finds), kept=kept,
        best=_euros(best, sign=True) if best is not None and best > 0 else "",
        best_note="la meilleure affaire affichée" if best is not None and best > 0 else "",
        segs=show_link("open", "À trier") + show_link("interested", f"Ma liste ({kept})") + show_link("all", "Tout"),
        show=_e(show),
        q=_e(q.get("q", "")), budget=_e(q.get("budget", "")),
        km=_e("" if km is None else f"{km:g}"), age=_e(q.get("age", "")),
        cat_opts=opts([("", "Toutes les catégories")]
                      + [(k, f"{CAT_LABEL.get(k, k)} ({n})") for k, n in categories(board.finds)], q.get("cat", "")),
        sort_opts=opts([(s, _SORT_LABEL[s]) for s in SORTS], sort),
        conf_opts=opts([("", "Toutes les estimations"), ("0.5", "Adossées au marché"),
                        ("1.0", "100 % prix réels")], "" if conf is None else f"{conf:g}"),
        nohs=" checked" if q.get("nohs") == "1" else "",
        cards="".join(_card(f, picks.get(f.uid)) for f in shown) or (
            "<div class='empty'><h2>Rien avec ces filtres</h2><p>Élargis le budget ou la distance, "
            "ou lance une recherche en direct ci-dessus.</p></div>"),
        busy=_e(board.busy),
        markers_json=json.dumps(markers).replace("</", "<\\/"),
        home_json=json.dumps(list(board.settings.home)),
        circle_inputs=hidden_circle, circle_clear_btn=clear_circle,
    )


_SORT_LABEL = {"savings": "Les plus rentables", "ratio": "Meilleur rapport", "price": "Les moins chères",
               "distance": "Les plus proches", "recent": "Vues récemment", "value": "Le plus gros matériel",
               "cut": "Prix déjà baissé", "sitting": "Ne part pas (à négocier)"}


def _state(picks, uid) -> str:
    row = picks.get(uid)
    return row["state"] if row else ""


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


# ---------- server ----------


class _Handler(BaseHTTPRequestHandler):
    board: Board = None

    def log_message(self, *a):
        pass

    def _local(self) -> bool:
        """The Host header names this machine (blocks DNS rebinding)."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        return host in _LOCAL_HOSTS

    def _same_origin_write(self) -> bool:
        """A write comes from this page: a JSON body (another site cannot send
        one without a preflight this server never answers) and, when the
        browser sends one, a local Origin."""
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return False
        origin = self.headers.get("Origin")
        return origin is None or urllib.parse.urlsplit(origin).hostname in {"127.0.0.1", "localhost", "::1"}

    def do_GET(self):
        if not self._local():
            return self._send(403, "text/plain", b"forbidden")
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/state":
            return self._json({"busy": self.board.busy})
        if parsed.path not in ("/", "/index.html"):
            return self._send(404, "text/plain", b"nope")
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        self._send(200, "text/html; charset=utf-8", _page(self.board, q).encode())

    def do_POST(self):
        if not (self._local() and self._same_origin_write()):
            return self._send(403, "text/plain", b"forbidden")
        parsed = urllib.parse.urlparse(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            return self._json({"ok": False}, 400)

        if parsed.path == "/pick":
            self.board.store.set_pick(str(data.get("uid", "")),
                                      str(data.get("state", "")),
                                      data.get("note"))
            return self._json({"ok": True})
        if parsed.path == "/sweep":
            terms = [t for t in str(data.get("terms", "")).split(",") if t.strip()]
            if terms and not self.board.busy:
                threading.Thread(
                    target=self.board.go_look, args=(terms,),
                    kwargs={"max_price": _num(data.get("max_price")),
                            "category": data.get("category") or None},
                    daemon=True).start()
            return self._json({"ok": True})
        self._send(404, "text/plain", b"nope")

    def _json(self, obj, code=200):
        self._send(code, "application/json", json.dumps(obj).encode())

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve(settings, host: str = "127.0.0.1", port: int = 8765):
    board = Board(settings)
    handler = type("Handler", (_Handler,), {"board": board})
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"TechFlip, tableau d’achat : http://{host}:{port}  ({len(board.finds)} offres chiffrées)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


_CSS = """
*{box-sizing:border-box}
:root{--bg:#F3EEE4;--surface:#FAF7F0;--elevated:#FFFDF8;--border:#DCD3C1;--rule:#E6DECF;
  --text:#1C2620;--muted:#5F6358;--faint:#9A9585;--accent:#1F3B2D;--on-accent:#F6F1E6;
  --brass:#9A7B3F;--profit:#2B5B3C;--warn:#8C6418;--risk:#7B2D33;--info:#2C4264;
  --tint:rgba(31,59,45,.06);
  --serif:"EB Garamond",Georgia,"Times New Roman",serif;
  --sans:"Source Sans 3","Segoe UI",system-ui,-apple-system,sans-serif}
@media (prefers-color-scheme:dark){:root{--bg:#111813;--surface:#172019;--elevated:#1D2820;
  --border:#2E3B31;--rule:#243028;--text:#ECE5D5;--muted:#A7A08C;--faint:#6E6B5E;
  --accent:#C9AE72;--on-accent:#14201A;--brass:#C9AE72;--profit:#A3C7A6;--warn:#D3A65A;
  --risk:#C98079;--info:#9DB1CF;--tint:rgba(201,174,114,.07)}}
html{background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.45 var(--sans);
  -webkit-font-smoothing:antialiased}
a{color:inherit}
.wrap{max-width:1180px;margin:0 auto;padding:0 24px}
header{border-bottom:1px solid var(--rule)}
.top{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;padding:22px 0 14px}
.brand{font:600 22px/1 var(--serif);letter-spacing:.4px}
.label{font:600 11.5px/15px var(--sans);letter-spacing:1.6px;text-transform:uppercase;color:var(--brass)}
h1{font:500 34px/38px var(--serif);letter-spacing:-.3px;margin:4px 0 0}
.stat{text-align:right}
.stat .money{font:600 28px/1 var(--serif);color:var(--profit)}
.stat small{display:block;color:var(--muted);font-size:14px;margin-top:4px}
.filters{padding:0 0 14px}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.row.sub{margin-top:8px}
.row.sub select,.row.sub input{font-size:14px;padding:6px 10px}
.q{flex:1 1 260px}.n{width:120px}
input,select,button{font:inherit;font-size:15px;color:var(--text);background:var(--surface);
  border:1px solid var(--border);border-radius:4px;padding:8px 11px}
input::placeholder{color:var(--faint)}
input:focus,select:focus{outline:2px solid var(--brass);outline-offset:-1px}
button{cursor:pointer}
button.go{background:var(--accent);border-color:var(--accent);color:var(--on-accent);
  font-weight:600;letter-spacing:.3px}
button.ghost{background:transparent}
label.chk{display:flex;gap:6px;align-items:center;color:var(--muted);font-size:14px}
.bar{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;
  padding:12px 0;border-top:1px solid var(--rule)}
.segs{display:flex;gap:18px}
.seg{text-decoration:none;color:var(--faint);font-weight:600}
.seg.on{color:var(--text);text-decoration:underline;text-underline-offset:5px}
.live{display:flex;gap:8px;flex:1 1 420px;justify-content:flex-end}
.live input{flex:1;max-width:420px}
#busy{color:var(--brass);font-size:14px;min-height:0}
#busy:not(:empty){padding:10px 0}
#map{height:380px;margin:20px 0 8px;border:1px solid var(--border);border-radius:6px;overflow:hidden}
.count{color:var(--muted);font-size:14px;margin:18px 0 4px}
.grid{display:grid;gap:0 32px;grid-template-columns:repeat(auto-fill,minmax(500px,1fr));padding-bottom:48px}
@media (max-width:620px){.grid{grid-template-columns:1fr}.wrap{padding:0 16px}
  h1{font-size:28px;line-height:32px}.stat .money{font-size:24px}
  .row.main{display:grid;grid-template-columns:1fr 1fr}.row.main .q,.row.main .go{grid-column:1/-1}
  .n{width:auto;min-width:0}.row.sub{display:grid;grid-template-columns:1fr 1fr}
  .row.sub .chk{grid-column:1/-1}.thumb{flex-basis:72px;height:72px}
  .live{flex-basis:100%}.live input{max-width:none}}
.card{display:flex;gap:16px;padding:18px 0;border-bottom:1px solid var(--rule)}
.card.is-hidden{opacity:.38}
.card.is-kept .keep{background:var(--accent);border-color:var(--accent);color:var(--on-accent)}
.thumb{flex:0 0 92px;height:92px;border-radius:2px;overflow:hidden;background:var(--rule);display:block}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.body{flex:1;min-width:0}
.head{display:flex;gap:12px;align-items:flex-start}
.what{flex:1;min-width:0}
h3{font:600 16px/21px var(--sans);margin:0 0 3px}
h3 a{text-decoration:none}
h3 a:hover{text-decoration:underline;text-underline-offset:3px}
.meta{margin:0;color:var(--muted);font-size:14px;font-variant-numeric:tabular-nums}
.meta b{color:var(--text);font-weight:600}
.was{color:var(--faint)}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin:0 5px 1px 0;background:var(--faint)}
.z-easy{background:var(--profit)}.z-med{background:var(--brass)}.z-hard{background:var(--info)}
.net{text-align:right;flex:0 0 auto}
.net span{display:block;font:600 24px/28px var(--serif);font-variant-numeric:tabular-nums}
.net.up span{color:var(--profit)}.net.down span{color:var(--risk)}
.net small{color:var(--faint);font-size:13px}
.pills{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 2px}
.pill{font:600 10.5px/14px var(--sans);letter-spacing:1.2px;text-transform:uppercase;padding:2px 7px;
  border:1px solid currentColor;border-radius:2px;cursor:help;white-space:nowrap}
.t-risk{color:var(--risk)}.t-warn{color:var(--warn)}.t-profit{color:var(--profit)}
.t-info{color:var(--info)}.t-muted{color:var(--faint)}
.lev{margin:6px 0 0;color:var(--profit);font-size:14px;font-style:italic}
details{margin:8px 0 6px}
summary{cursor:pointer;color:var(--brass);font:600 11.5px/15px var(--sans);letter-spacing:1.6px;
  text-transform:uppercase;list-style:none}
summary::-webkit-details-marker{display:none}
summary span{color:var(--faint);letter-spacing:0;text-transform:none;font-weight:400;font-size:13px}
.ledger{margin:8px 0 4px;max-width:420px}
.lrow{display:flex;justify-content:space-between;padding:4px 0;font-size:14px;color:var(--muted);
  font-variant-numeric:tabular-nums}
.lrow span:last-child{color:var(--text)}
.lrow.total{border-top:1px solid var(--rule);margin-top:4px;padding-top:7px;color:var(--text);font-weight:600}
.lrow.total span:last-child{font:600 18px/1 var(--serif);color:var(--profit)}
.parts{margin:8px 0 0;padding-left:18px;color:var(--muted);font-size:13px}
.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:8px}
.actions button{font-size:13.5px;padding:6px 12px}
.hide:hover{color:var(--risk);border-color:var(--risk)}
.note{flex:1 1 140px;font-size:13.5px;padding:6px 10px}
.empty{text-align:center;padding:56px 16px;color:var(--muted)}
.empty h2{font:500 26px/30px var(--serif);color:var(--text);margin:0 0 6px}
.pin{font:600 12px/1 var(--sans);color:#fff;padding:4px 7px;border-radius:2px;white-space:nowrap;
  box-shadow:0 1px 3px rgba(0,0,0,.25);font-variant-numeric:tabular-nums}
.pin.z-easy{background:#2B5B3C}.pin.z-med{background:#9A7B3F}.pin.z-hard{background:#2C4264}
.leaflet-popup-content{font:14px/1.4 var(--sans)}
.leaflet-popup-content b{font:600 16px var(--serif)}
"""

_JS = """
function pick(el, state, note){
  const card = el.closest('.card'), uid = card.dataset.uid;
  const already = state === 'interested' && card.classList.contains('is-kept') && note === undefined;
  const next = already ? 'none' : state;
  fetch('/pick', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({uid, state: next, note: note ?? null})})
   .then(() => {
     card.classList.toggle('is-kept', next === 'interested');
     card.classList.toggle('is-hidden', next === 'hidden');
     card.querySelector('.keep').textContent = next === 'interested' ? 'Gardée' : 'Garder';
   });
}
function goLook(){
  const t = document.getElementById('sweepterms').value.trim();
  if(!t) return;
  document.getElementById('busy').textContent = 'Recherche en cours sur Leboncoin et 2ememain…';
  fetch('/sweep', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({terms: t, max_price: document.querySelector('[name=budget]').value,
                          category: document.querySelector('[name=cat]').value})})
   .then(() => poll());
}
function poll(){
  fetch('/state').then(r => r.json()).then(s => {
    if(s.busy){ document.getElementById('busy').textContent = s.busy; setTimeout(poll, 2000); }
    else { location.reload(); }
  });
}
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const sign = (n) => (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(n);
document.addEventListener('DOMContentLoaded', () => {
  const el = document.getElementById('map');
  if (!el) return;
  if (!window.L) { el.style.display = 'none'; return; }   // offline: no map, no empty box
  const map = L.map('map', {scrollWheelZoom: false});
  const bounds = L.latLngBounds();
  let any = false;
  // OpenStreetMap's own tiles: CARTO's now require a key.
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'}).addTo(map);
  const cluster = L.markerClusterGroup({maxClusterRadius: 40});
  const zone = {EASY: 'z-easy', MEDIUM: 'z-med', HARD: 'z-hard'};
  markersData.forEach(m => {
    const icon = L.divIcon({className: '', iconSize: null,
      html: `<span class="pin ${zone[m.zone] || ''}">${sign(m.net)} €</span>`});
    cluster.addLayer(L.marker([m.lat, m.lng], {icon}).bindPopup(
      `<b>${sign(m.net)} €</b><br><a href="${m.url}" target="_blank" rel="noopener">${m.title}</a><br>${m.price} · ${m.city}`));
    bounds.extend([m.lat, m.lng]);
    any = true;
  });
  const params = new URLSearchParams(location.search);
  const ulat = parseFloat(params.get('ulat')), ulng = parseFloat(params.get('ulng')), urad = parseFloat(params.get('urad'));
  const ring = {color: css('--brass'), fillColor: css('--brass'), fillOpacity: .08, weight: 2, interactive: false};
  let circle = null;
  if (!isNaN(ulat) && !isNaN(ulng) && !isNaN(urad)) {
    circle = L.circle([ulat, ulng], {...ring, radius: urad * 1000}).addTo(map);
    bounds.extend(circle.getBounds());
    any = true;
  }
  if (any) {
    map.addLayer(cluster);
    // Leaflet measures the pane when fitBounds runs; measure again once the
    // layout has settled, or it settles on the whole planet.
    const refit = () => { map.invalidateSize(); map.fitBounds(bounds, {padding: [24, 24]}); };
    refit(); setTimeout(refit, 0);
    addEventListener('load', refit); addEventListener('resize', refit);
  } else {
    map.setView(HOME, 9);
  }
  map.on('click', (e) => {
    const rad = 50;
    if (circle) map.removeLayer(circle);
    circle = L.circle(e.latlng, {...ring, radius: rad * 1000}).addTo(map);
    window.activeCircle = circle;
    L.popup().setLatLng(e.latlng).setContent(
      `<div style="text-align:center"><div style="margin-bottom:8px">Chercher dans cette zone&nbsp;?</div>
       <input type="number" id="radInput" value="${rad}" min="1" max="2000" style="width:64px"
         oninput="window.activeCircle && window.activeCircle.setRadius(this.value * 1000)"> km
       <div style="margin-top:8px"><button class="go" onclick="searchHere(${e.latlng.lat}, ${e.latlng.lng})">Chercher</button></div></div>`
    ).openOn(map);
  });
});
function searchHere(lat, lng){
  const url = new URL(location);
  url.searchParams.set('ulat', lat); url.searchParams.set('ulng', lng);
  url.searchParams.set('urad', document.getElementById('radInput').value);
  url.searchParams.delete('km');
  location = url.toString();
}
function clearCircle(){
  const url = new URL(location);
  ['ulat', 'ulng', 'urad'].forEach(k => url.searchParams.delete(k));
  location = url.toString();
}
"""

_SHELL = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TechFlip · Tableau d’achat</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=EB+Garamond:wght@500;600&family=Source+Sans+3:wght@400;600&display=swap">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" crossorigin=""/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" crossorigin=""/>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js" crossorigin=""></script>
<style>{css}</style></head>
<body>
<header><div class="wrap">
  <div class="top">
    <div>
      <div class="brand">TechFlip</div>
      <div class="label" style="margin-top:6px">Tableau d’achat · depuis {home_label}</div>
      <h1>Les affaires du moment</h1>
    </div>
    <div class="stat"><div class="money">{best}</div><small>{best_note}</small></div>
  </div>
  <form method="get" class="filters">
    <input type="hidden" name="show" value="{show}">{circle_inputs}
    <div class="row main">
      <input class="q" type="text" name="q" value="{q}" placeholder="xbox, rtx 3060, pc gamer…">
      <input class="n" type="number" name="budget" value="{budget}" placeholder="Budget €">
      <input class="n" type="number" name="km" value="{km}" placeholder="Rayon km">
      <select name="cat">{cat_opts}</select>
      <select name="sort">{sort_opts}</select>
      <button class="go" type="submit">Filtrer</button>
    </div>
    <div class="row sub">
      <select name="conf">{conf_opts}</select>
      <input class="n" type="number" name="age" value="{age}" placeholder="Âge max (jours)">
      <label class="chk"><input type="checkbox" name="nohs" value="1"{nohs}> Cacher les pannes</label>
      {circle_clear_btn}
    </div>
  </form>
</div></header>
<main class="wrap">
  <div class="bar">
    <nav class="segs">{segs}</nav>
    <form class="live" onsubmit="goLook();return false">
      <input id="sweepterms" type="text" placeholder="Chercher en direct (ex : xbox series s, pc gamer)">
      <button type="submit" class="ghost">Aller chercher</button>
    </form>
  </div>
  <div id="busy">{busy}</div>
  <div id="map"></div>
  <p class="count">{n_shown} affichées sur {n_total} chiffrées · gain net, trajet ou envoi déduit</p>
  <section class="grid">{cards}</section>
</main>
<script>
  const markersData = {markers_json};
  const HOME = {home_json};
</script>
<script>{js}</script>
</body></html>
"""
