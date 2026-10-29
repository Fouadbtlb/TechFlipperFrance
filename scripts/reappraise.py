"""Value stored listings with the current rules and save the appraisals, so the
app has deals to show after an `import`. No scraping, no AI photo check, no
seller lookups, no Telegram: it only writes appraisals to TECHFLIP_DB.

Usage: TECHFLIP_DB=techflip-app.db python scripts/reappraise.py [days]
"""
import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from techflip.config import load_settings
from techflip.decision import policy_from_settings
from techflip.domain import Listing
from techflip.geo import Locator
from techflip.pricing.catalog import load_catalog
from techflip.pricing.identify import components_of
from techflip.pricing.sold import load_sold
from techflip.pricing.tracker import PriceTracker
from techflip.storage import Store
from techflip.valuation import Rejection, Valuer

days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
s = load_settings()
store = Store(s.db_path)
catalog = load_catalog(s.pricebook_path)
tracker = PriceTracker(store, catalog, s.min_comparables, s.window_days,
                       owner_sales=load_sold(s.sold_path))
valuer = Valuer(s, store, catalog, tracker, Locator(origin=s.home), policy_from_settings(s),
                {x.name: x for x in s.searches}, origins=lambda: [s.home],
                classify=None, sellers=None)

since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
rows = store.conn.execute(
    "SELECT raw_json FROM listings WHERE status='active' AND price IS NOT NULL "
    "AND date(last_seen) >= ?", (since,)).fetchall()
saved = rejected = 0
for r in rows:
    l = Listing.from_dict(json.loads(r["raw_json"]))
    v = valuer.value(l, components_of(l, catalog))
    if isinstance(v, Rejection):
        store.clear_appraisal(l.uid)
        rejected += 1
        continue
    store.save_appraisal(l.uid, true_value=v.true_value, price=l.price, confidence=v.confidence,
                         category=v.category, appraisal=v.appraisal)
    saved += 1
print(f"db={s.db_path} since={since} listings={len(rows)} appraised={saved} rejected={rejected}")
