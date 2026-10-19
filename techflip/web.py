"""Local web board: every offer worth a look, on one page, for a human to sort.

Telegram is a firehose with one bit of state (sent / not sent) and no way to say
"keep this one, I'll go Saturday". The whole pool is also far larger than the
handful of ads that ever cleared the alert bar, and most of what is genuinely
worth buying never clears it: it is simply a fair price on a thing you want.

So this serves the stored pool as a shopping board -- filterable by budget,
category, distance and text, with a shortlist you own. No framework, no CDN, no
build step: one stdlib HTTP server and one file, because a tool you have to
deploy is a tool you stop running.
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

log = logging.getLogger(__name__)

CAT_LABEL = {"pc": "PC complet", "console": "Console", "gpu": "Carte graphique",
             "cpu": "Processeur", "ram": "RAM", "storage": "Stockage",
             "psu": "Alimentation", "motherboard": "Carte mere",
             "monitor": "Ecran", "controller": "Manette", "game": "Jeu",
             "cooler": "Refroidissement", "case": "Boitier"}

FLAG_LABEL = {
    "bait": ("arnaque probable", ("Prix trop bas pour etre vrai: annonce bidon, "
                                 "photo volee, ou paiement par virement.")),
    "broken": ("en panne", "L'annonce dit HS / ne s'allume pas. Valeur deja reduite."),
    "sales_copy": ("texte fiche produit", ("Description copiee du site du fabricant, "
                                          "pas ecrite par un vendeur. Exige une vraie photo.")),
    "partial": ("pieces non chiffrees", ("Une piece citee n'est pas au catalogue: "
                                        "la valeur affichee est un plancher.")),
    "stale": ("ancienne", "Pas revue depuis plus de 10 jours: probablement vendue."),
    "cut": ("prix baisse", "Le vendeur a deja baisse son prix. Il rebaissera."),
    "sitting": ("ne part pas", ("Toujours en ligne des semaines apres sa parution: "
                               "le marche a refuse ce prix. Negocie.")),
    "laptop": ("portable", ("Chiffre avec des prix de pieces DESKTOP. Un GPU de "
                           "portable vaut nettement moins: valeur a diviser.")),
}

ZONE_DOT = {"EASY": "z-easy", "MEDIUM": "z-med", "HARD": "z-hard"}


class Board:
    """Holds the scan, so a page load is a filter over memory, not a rescan."""

    def __init__(self, settings):
        self.settings = settings
        self.store = Store(settings.db_path)
        self.catalog = load_catalog(settings.pricebook_path)
        # De-biased on the board, plain in the alert path. Ads still on sale
        # weeks later did not sell at that price, so they are evidence about
        # what sellers hope for; dropping them makes "valeur" mean something
        # closer to what the thing actually goes for. Kept off the alert path
        # until it has been judged on real data.
        self.tracker = PriceTracker(self.store, self.catalog,
                                    settings.min_comparables, settings.window_days,
                                    stale_days=settings.stale_days,
                                    sold=load_sold(settings.sold_path))
        self.locator = Locator()
        self._lock = threading.Lock()
        self.finds = []
        self.busy = ""
        self.refresh()

    def refresh(self):
        with self._lock:
            self.finds = scan(self.store, self.catalog, self.tracker, self.locator,
                              easy_km=self.settings.easy_km,
                              medium_km=self.settings.medium_km,
                              realization=self.settings.realization_factor)
        return len(self.finds)

    def go_look(self, terms, max_price=None, category=None):
        """Run a live search then rescan. Long, so the UI polls `busy`."""
        from .pipeline import Pipeline
        self.busy = "recherche en cours: " + ", ".join(terms)
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


def _card(f, pick) -> str:
    state = pick["state"] if pick else ""
    note = (pick["note"] if pick else "") or ""
    good = f.savings > 0 and not f.is_bait
    badge = (f"<span class='save {'up' if good else 'down'}'>"
             f"{'+' if f.savings > 0 else ''}{f.savings:.0f}€</span>")
    dist = f"{f.distance:.0f} km" if f.distance is not None else "distance ?"
    age = (f"vue il y a {f.age_days:.0f} j" if f.age_days and f.age_days >= 1
           else "vue aujourd'hui")
    flags = "".join(
        f"<span class='flag f-{k}' title='{_e(FLAG_LABEL[k][1])}'>{_e(FLAG_LABEL[k][0])}</span>"
        for k in f.flags if k in FLAG_LABEL)
    parts = "".join(f"<span class='part'>{_e(p)}</span>" for p in f.parts[:6])
    lines = "".join(f"<li>{_e(l)}</li>" for l in f.lines)
    img = (f"<img loading='lazy' referrerpolicy='no-referrer' src='{_e(f.image)}' alt=''>"
           if f.image else "<div class='noimg'>pas de photo</div>")
    was = (f"<span class='was'>{f.price_cut['first']:.0f}€</span>" if f.price_cut else "")
    lev = f"<div class='lev'>{_e(f.leverage)}</div>" if f.leverage else ""

    return f"""
<article class="card {'is-hidden' if state == 'hidden' else ''} {'is-kept' if state == 'interested' else ''}" data-uid="{_e(f.uid)}">
  <a class="thumb" href="{_e(f.url)}" target="_blank" rel="noopener noreferrer">{img}</a>
  <div class="body">
    <div class="toprow">
      <span class="price">{f.price:.0f}€</span>{was}{badge}
      <span class="val">valeur ~{f.value:.0f}€</span>
    </div>
    <h3><a href="{_e(f.url)}" target="_blank" rel="noopener noreferrer">{_e(f.title)}</a></h3>
    <div class="meta">
      <span class="dot {ZONE_DOT.get(f.zone, '')}"></span>{_e(dist)}
      &middot; {_e(f.city or '?')} &middot; {_e(f.source)} &middot; {_e(age)}
    </div>
    <div class="chips">{parts}{flags}</div>{lev}
    <details><summary>detail du calcul ({f.n_priced} piece(s), confiance {f.confidence:.0%})</summary>
      <ul>{lines}</ul></details>
    <div class="actions">
      <button class="keep" onclick="pick(this,'interested')">{'garde' if state == 'interested' else 'ca m interesse'}</button>
      <button class="hide" onclick="pick(this,'hidden')">masquer</button>
      <input class="note" placeholder="note" value="{_e(note)}" onchange="pick(this,'interested',this.value)">
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
    # they are visible and one click from being cleared -- a hidden default that
    # silently drops listings would be worse than no default at all.
    ulat = _num(q.get("ulat"))
    ulng = _num(q.get("ulng"))
    urad = _num(q.get("urad"))

    first_visit = not any(q.get(k) for k in ("q", "budget", "cat", "km", "age",
                                             "sort", "show", "conf", "nohs",
                                             "ulat", "ulng", "urad"))
    km = _num(q.get("km")) if not first_visit else 120.0
    if ulat is not None and ulng is not None and urad is not None:
        km = None
    conf = _num(q.get("conf")) if not first_visit else 0.5

    sel = filter_finds(
        finds,
        budget=_num(q.get("budget")),
        category=q.get("cat") or None,
        max_km=km,
        min_savings=_num(q.get("min")),
        kind=q.get("kind") or None,
        query=q.get("q") or None,
        max_age_days=_num(q.get("age")),
        hide_broken=q.get("nohs") == "1",
        min_confidence=conf,
        ulat=ulat,
        ulng=ulng,
        urad=urad,
    )
    sort = q.get("sort") if q.get("sort") in SORTS else "savings"
    sel = rank(sel, sort)

    cats = categories(board.finds)
    cat_opts = "".join(
        f"<option value='{_e(k)}'{' selected' if q.get('cat') == k else ''}>"
        f"{_e(CAT_LABEL.get(k, k))} ({n})</option>" for k, n in cats)
    sort_opts = "".join(
        f"<option value='{s}'{' selected' if sort == s else ''}>{_e(_SORT_LABEL[s])}</option>"
        for s in SORTS)
    show_opts = "".join(
        f"<option value='{k}'{' selected' if show == k else ''}>{_e(v)}</option>"
        for k, v in (("open", "a trier"), ("interested", "ma liste"), ("all", "tout")))


    cards = "".join(_card(f, picks.get(f.uid)) for f in sel[:400])
    kept = sum(1 for p in picks.values() if p["state"] == "interested")

    markers = []
    for f in sel[:400]:
        if f.lat is not None and f.lng is not None:
            markers.append({
                "lat": f.lat, "lng": f.lng, 
                "title": _e(f.title), "url": _e(f.url), "price": f.price, 
                "uid": f.uid, "source": _e(f.source), "city": _e(f.city or "?")
            })
    markers_json = json.dumps(markers).replace("</", "<\\/")

    circle_inputs = ""
    circle_clear_btn = ""
    if ulat is not None and ulng is not None and urad is not None:
        circle_inputs = f'<input type="hidden" name="ulat" value="{ulat}"><input type="hidden" name="ulng" value="{ulng}"><input type="hidden" name="urad" value="{urad}">'
        circle_clear_btn = f'<button type="button" onclick="clearCircle()" class="clear-btn">&times; Zone {urad:g}km</button>'

    return _SHELL.format(
        css=_CSS, js=_JS,
        n_shown=len(sel), n_total=len(board.finds), kept=kept,
        cat_opts=cat_opts, sort_opts=sort_opts, show_opts=show_opts,
        q=_e(q.get("q", "")), budget=_e(q.get("budget", "")),
        km=_e("" if km is None else f"{km:g}"), age=_e(q.get("age", "")),
        conf_opts="".join(
            f"<option value='{'' if v is None else v}'"
            f"{' selected' if conf == v else ''}>{_e(lbl)}</option>"
            for v, lbl in ((None, "toutes estimations"),
                           (0.5, "adosse au marche"),
                           (1.0, "100% prix reels"))),
        nohs=" checked" if q.get("nohs") == "1" else "",
        cards=cards or "<p class='empty'>Rien avec ces filtres. Elargis le budget "
                       "ou la distance, ou lance une recherche live ci-dessus.</p>",
        busy=_e(board.busy),
        markers_json=markers_json,
        circle_inputs=circle_inputs,
        circle_clear_btn=circle_clear_btn,
    )


_SORT_LABEL = {"savings": "meilleure affaire", "ratio": "meilleur rapport",
               "price": "moins cher", "distance": "plus proche",
               "recent": "plus recent", "value": "plus gros materiel",
               "cut": "prix deja baisse", "sitting": "ne part pas (a negocier)"}


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

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/state":
            return self._json({"busy": self.board.busy})
        if parsed.path not in ("/", "/index.html"):
            return self._send(404, "text/plain", b"nope")
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        self._send(200, "text/html; charset=utf-8", _page(self.board, q).encode())

    def do_POST(self):
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
    print(f"TechFlip board: http://{host}:{port}  ({len(board.finds)} offres chiffrees)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


_CSS = """
*{box-sizing:border-box}
:root{--bg:#0e1116;--card:#171b22;--line:#252b36;--txt:#e6e9ef;--dim:#8b93a3;
      --up:#3ddc84;--down:#ff6b6b;--acc:#4c8dff}
@media (prefers-color-scheme:light){
  :root{--bg:#f4f6fa;--card:#fff;--line:#dfe3ea;--txt:#161a20;--dim:#5f6878;
        --up:#0a8f4d;--down:#c62828;--acc:#1256c4}}
body{margin:0;background:var(--bg);color:var(--txt);
     font:15px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);
       border-bottom:1px solid var(--line);padding:12px 16px}
h1{font-size:17px;margin:0 0 10px;letter-spacing:.3px}
h1 small{color:var(--dim);font-weight:400;margin-left:8px;letter-spacing:0}
form{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
input,select,button{background:var(--card);color:var(--txt);border:1px solid var(--line);
                    border-radius:8px;padding:7px 10px;font:inherit;font-size:14px}
input[type=text],input[type=number]{min-width:0}
.w-q{flex:1 1 200px}.w-s{width:110px}
button{cursor:pointer}
button.go{background:var(--acc);border-color:var(--acc);color:#fff;font-weight:600}
label.chk{display:flex;gap:6px;align-items:center;color:var(--dim);font-size:14px}
.grid{display:grid;gap:12px;padding:16px;
      grid-template-columns:repeat(auto-fill,minmax(340px,1fr))}
.card{display:flex;gap:12px;background:var(--card);border:1px solid var(--line);
      border-radius:12px;padding:10px;overflow:hidden}
.card.is-hidden{opacity:.35}
.card.is-kept{border-color:var(--up);box-shadow:0 0 0 1px var(--up) inset}
.thumb{flex:0 0 104px;height:104px;border-radius:8px;overflow:hidden;background:#0b0e13;
       display:block}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}
.noimg{display:grid;place-items:center;height:100%;color:var(--dim);font-size:11px;
       text-align:center;padding:6px}
.body{flex:1;min-width:0}
.toprow{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.price{font-size:21px;font-weight:700}
.save{font-weight:700;font-size:14px}
.save.up{color:var(--up)}.save.down{color:var(--down)}
.was{color:var(--dim);text-decoration:line-through;font-size:13px}
.lev{color:var(--up);font-size:12px;margin:0 0 5px}
.f-cut{background:var(--up);color:#062514}
.f-sitting{background:var(--acc);color:#fff}
.f-laptop{background:#f5a524}
.val{color:var(--dim);font-size:13px;margin-left:auto}
h3{font-size:14px;font-weight:600;margin:4px 0 4px;line-height:1.3}
h3 a{color:var(--txt);text-decoration:none}
h3 a:hover{text-decoration:underline}
.meta{color:var(--dim);font-size:12.5px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px;
     background:var(--dim);vertical-align:middle}
.z-easy{background:var(--up)}.z-med{background:#f5a524}.z-hard{background:var(--down)}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin:6px 0}
.part,.flag{font-size:11px;padding:2px 7px;border-radius:20px;border:1px solid var(--line);
            color:var(--dim);white-space:nowrap}
.flag{cursor:help;border-color:transparent;color:#111}
.f-bait{background:var(--down);color:#fff}
.f-broken{background:#f5a524}.f-sales_copy{background:#f5a524}
.f-partial{background:var(--line);color:var(--dim)}
.f-stale{background:var(--line);color:var(--dim)}
details{margin:2px 0 6px}
summary{color:var(--dim);font-size:12px;cursor:pointer}
details ul{margin:6px 0 0;padding-left:18px;color:var(--dim);font-size:12.5px}
.actions{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.actions button{font-size:12.5px;padding:5px 9px}
.keep:hover{border-color:var(--up);color:var(--up)}
.hide:hover{border-color:var(--down);color:var(--down)}
.note{flex:1 1 90px;font-size:12.5px;padding:5px 8px}
.empty{color:var(--dim);padding:40px 16px;text-align:center}
#busy{color:var(--acc);font-size:13px;padding:0 16px}
#map{height:400px;width:calc(100% - 32px);margin:16px;border:1px solid var(--line);border-radius:12px;overflow:hidden;box-shadow:0 2px 10px rgba(0,0,0,0.05)}
.clear-btn{background:var(--down);border-color:var(--down);color:#fff;font-weight:600}
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
   });
}
function goLook(){
  const t = document.getElementById('sweepterms').value.trim();
  if(!t) return;
  document.getElementById('busy').textContent = 'recherche en cours sur les deux sites...';
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
document.addEventListener("DOMContentLoaded", () => {
  if (document.getElementById('map')) {
    const map = L.map('map');
    let bounds = L.latLngBounds();
    let hasValidMarkers = false;

    // OpenStreetMap's own tiles, not CARTO's: CARTO started requiring an API
    // key and every tile came back stamped "API KEY REQUIRED", which made the
    // map unreadable. OSM asks for attribution and nothing else.
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(map);

    const clusterGroup = L.markerClusterGroup({
      maxClusterRadius: 40
    });

    markersData.forEach(m => {
      if (m.lat && m.lng) {
        const marker = L.marker([m.lat, m.lng]);
        marker.bindPopup(`<b>${m.price}€</b><br><a href="${m.url}" target="_blank">${m.title}</a><br>Source: ${m.source} (${m.city})`);
        clusterGroup.addLayer(marker);
        bounds.extend([m.lat, m.lng]);
        hasValidMarkers = true;
      }
    });

    const params = new URLSearchParams(window.location.search);
    const ulat = parseFloat(params.get('ulat'));
    const ulng = parseFloat(params.get('ulng'));
    const urad = parseFloat(params.get('urad'));
    let searchCircle = null;
    
    if (!isNaN(ulat) && !isNaN(ulng) && !isNaN(urad)) {
      searchCircle = L.circle([ulat, ulng], {
        radius: urad * 1000,
        color: 'var(--acc)',
        fillColor: 'var(--acc)',
        fillOpacity: 0.1,
        weight: 2,
        interactive: false
      }).addTo(map);
      bounds.extend(searchCircle.getBounds());
      hasValidMarkers = true;
    }

    if (hasValidMarkers) {
      map.addLayer(clusterGroup);
      map.fitBounds(bounds);
      // Leaflet measures the container when fitBounds runs. If the pane is
      // still laying out, it measures nothing and settles on zoom 0, which
      // draws the whole planet with one cluster in the middle -- 387 markers
      // inside a 100 km box, rendered as a world map. Re-measure once the
      // layout has settled, and again whenever the window changes size.
      const refit = () => { map.invalidateSize(); map.fitBounds(bounds); };
      setTimeout(refit, 0);
      window.addEventListener('load', refit);
      window.addEventListener('resize', refit);
    } else {
      map.setView([50.6292, 3.0573], 9);
    }

    map.on('click', function(e) {
      const rad = 50;
      if (searchCircle) { map.removeLayer(searchCircle); }
      searchCircle = L.circle(e.latlng, {
        radius: rad * 1000, color: 'var(--acc)', fillColor: 'var(--acc)', fillOpacity: 0.1, weight: 2, interactive: false
      }).addTo(map);
      
      window.activeSearchCircle = searchCircle;
      
      L.popup()
       .setLatLng(e.latlng)
       .setContent(`<div style="text-align:center;font-family:system-ui">
          <div style="margin-bottom:8px">Chercher dans cette zone ?</div>
          <button onclick="searchHere(${e.latlng.lat}, ${e.latlng.lng})" style="background:var(--acc);color:#fff;border:none;padding:5px 10px;border-radius:4px;cursor:pointer">Chercher</button>
          <div style="margin-top:8px"><input type="number" id="radInput" value="${rad}" min="1" max="2000" oninput="if(window.activeSearchCircle) window.activeSearchCircle.setRadius(this.value * 1000)" style="width:60px;padding:3px;border:1px solid #ccc;border-radius:4px"> km</div>
        </div>`)
       .openOn(map);
    });
  }
});

function searchHere(lat, lng) {
  const rad = document.getElementById('radInput').value;
  const url = new URL(window.location);
  url.searchParams.set('ulat', lat);
  url.searchParams.set('ulng', lng);
  url.searchParams.set('urad', rad);
  url.searchParams.delete('km');
  window.location = url.toString();
}

function clearCircle() {
  const url = new URL(window.location);
  url.searchParams.delete('ulat');
  url.searchParams.delete('ulng');
  url.searchParams.delete('urad');
  window.location = url.toString();
}
"""

_SHELL = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TechFlip - offres</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" crossorigin=""/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" crossorigin=""/>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js" crossorigin=""></script>
<style>{css}</style></head>
<body>
<header>
  <h1>TechFlip <small>{n_shown} affichees sur {n_total} chiffrees &middot; {kept} gardees</small></h1>
  <form method="get">
    <input class="w-q" type="text" name="q" value="{q}" placeholder="xbox, rtx 3060, pc gamer...">
    <input class="w-s" type="number" name="budget" value="{budget}" placeholder="budget max">
    <select name="cat"><option value="">toutes categories</option>{cat_opts}</select>
    <input class="w-s" type="number" name="km" value="{km}" placeholder="km max">
    <input class="w-s" type="number" name="age" value="{age}" placeholder="vue depuis (j)">
    <select name="conf">{conf_opts}</select>
    <select name="sort">{sort_opts}</select>
    <select name="show">{show_opts}</select>
    <label class="chk"><input type="checkbox" name="nohs" value="1"{nohs}>cacher les HS</label>
    {circle_inputs}
    <button class="go" type="submit">filtrer</button>
    {circle_clear_btn}
  </form>
  <form onsubmit="goLook();return false" style="margin-top:8px">
    <input class="w-q" id="sweepterms" type="text" placeholder="chercher en direct sur leboncoin + 2ememain (ex: xbox series s, pc gamer)">
    <button type="submit">aller chercher maintenant</button>
  </form>
</header>
<div id="busy">{busy}</div>
<div id="map"></div>
<main class="grid">{cards}</main>
<script>
  const markersData = {markers_json};
</script>
<script>{js}</script>
</body></html>
"""
