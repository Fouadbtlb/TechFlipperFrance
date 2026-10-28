"""Turn stored appraisals into what one subscriber sees.

Every number here is computed for the viewer: distance from THEIR home, THEIR
logistics, THEIR bar. Nothing location-specific is precomputed for anyone else.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from ..config import Settings
from ..decision import ZonePolicy
from ..storage import Store
from ..viewer import Judgement, Viewer, judge, policy_for

SORTS = ("profit", "distance", "recent")
CATEGORIES = ("console", "pc", "gpu", "cpu", "laptop", "phone", "monitor", "parts",
              "accessory", "other")


def default_policy(settings: Settings) -> ZonePolicy:
    return ZonePolicy(
        bars={"EASY": settings.easy_bar, "MEDIUM": settings.medium_bar, "HARD": settings.hard_bar},
        min_conf={"EASY": 0.0, "MEDIUM": settings.min_conf_medium, "HARD": settings.min_conf_hard},
    )


def viewer_for(user, settings: Settings) -> Viewer | None:
    if user["home_lat"] is None or user["home_lng"] is None:
        return None
    return Viewer(
        home=(user["home_lat"], user["home_lng"]),
        policy=policy_for(user["min_profit"], default_policy(settings)),
        easy_km=settings.easy_km, medium_km=settings.medium_km,
        cost_per_km=settings.cost_per_km,
        radius_km=user["radius_km"],
        include_shipping=bool(user["include_shipping"]),
        categories=frozenset(json.loads(user["categories"] or "[]")),
    )


def since_iso(max_age_days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()


# Below this, or with a serious risk signal, a deal goes to "À vérifier"
# instead of mixing with the solid ones.
RELIABLE_CONFIDENCE = 0.4
BUCKETS = ("reliable", "check")


def is_reliable(row) -> bool:
    return (row["confidence"] or 0) >= RELIABLE_CONFIDENCE and risk_level(_appraisal(row)) != "high"


def deals_for(store: Store, viewer: Viewer, max_age_days: int, hidden: set[str] = frozenset(),
              category: str | None = None, uids=None,
              bucket: str | None = None) -> list[tuple[dict, Judgement]]:
    best: dict[str, tuple] = {}
    for row in store.candidates(since_iso(max_age_days), 0.0, uids=uids):
        if row["uid"] in hidden:
            continue
        if category and row["category"] != category:
            continue
        if bucket and (bucket == "reliable") != is_reliable(row):
            continue
        j = judge(row, viewer)
        if not j.alert:
            continue
        # A reposted item shows once: its latest listing.
        group = row["repost_of"] or row["uid"]
        kept = best.get(group)
        if kept is None or (row["first_seen"] or "") > (kept[0]["first_seen"] or ""):
            best[group] = (row, j)
    return list(best.values())


def sort_deals(items, sort: str):
    if sort == "distance":
        key = lambda it: (it[1].distance_km is None, it[1].distance_km or 0, -(it[1].net or 0))  # noqa: E731
    elif sort == "recent":
        key = lambda it: _neg_ts(it[0]["first_seen"])  # noqa: E731
    else:
        key = lambda it: -(it[1].net or 0)  # noqa: E731
    return sorted(items, key=key)


def _neg_ts(iso: str | None) -> float:
    try:
        return -datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _appraisal(row) -> dict:
    return json.loads(row["appraisal"]) if row["appraisal"] else {}


def _raw(row) -> dict:
    return json.loads(row["raw_json"]) if row["raw_json"] else {}


def risk_level(appr: dict) -> str:
    risk = appr.get("risk") or 0
    flags = (appr.get("seller") or {}).get("flags") or []
    if risk >= 6 or any(f.get("level") == "risk" for f in flags):
        return "high"
    if risk >= 3 or flags:
        return "medium"
    return "low"


def _r(x, nd=0):
    return None if x is None else round(float(x), nd)


def card(row, j: Judgement) -> dict:
    appr = _appraisal(row)
    images = _raw(row).get("image_urls") or []
    prev = row["last_price"]
    return {
        "uid": row["uid"],
        "title": row["title"],
        "price": _r(row["price"]),
        "prev_price": _r(prev) if prev and prev > row["price"] else None,
        "value": _r(row["true_value"]),
        "net": _r(j.net),
        "zone": j.decision.zone,
        "distance_km": _r(j.distance_km),
        "logistics": _r(j.logistics),
        "mode": j.mode,
        "city": row["city"],
        "category": row["category"],
        "thumb": images[0] if images else None,
        "published_at": row["published_at"],
        "first_seen": row["first_seen"],
        "confidence": _r(row["confidence"], 2),
        "risk": risk_level(appr),
        "lat": row["lat"],
        "lng": row["lng"],
        "source": row["source"],
        "reliable": is_reliable(row),
        "reposts": row["reposts"] or 0,
        "days_to_sell": appr.get("days_to_sell"),
    }


def pin(row, j: Judgement) -> dict:
    return {"uid": row["uid"], "lat": row["lat"], "lng": row["lng"], "net": _r(j.net),
            "zone": j.decision.zone, "category": row["category"]}


def _round5(x: float) -> int:
    return int(x // 5 * 5)


def negotiation(row, j: Judgement, viewer: Viewer) -> dict | None:
    """The most this viewer should pay to keep their own margin, an opening
    offer, and a polite message to the seller (who is addressed as "vous")."""
    value, price, logistics = row["true_value"], row["price"], j.logistics
    if value is None or price is None or logistics is None:
        return None
    bar = viewer.policy.bars[j.decision.zone]
    max_price = _round5(value - logistics - bar)
    if max_price <= 0:
        return None
    # Room to ask depends on the listing's own signals, never below 75 % of the ask.
    reposts = row["reposts"] or 0
    pct = 0.82 if reposts else 0.88
    opening = min(_round5(max(0.75 * price, min(price * pct, max_price))), max_price)
    if opening >= price:
        opening = None
    title = (row["title"] or "article")[:60]
    if j.mode == "ship":
        how = "Je peux régler tout de suite avec le paiement sécurisé et l’envoi."
    else:
        how = "Je peux passer le récupérer rapidement et payer avec le paiement sécurisé."
    ask = f" Seriez-vous d’accord pour {opening}\u00a0€\u00a0?" if opening else ""
    message = f"Bonjour, votre annonce « {title} » est-elle toujours disponible\u00a0? {how}{ask} Merci et bonne journée."
    return {"max_price": max_price, "opening": opening, "message": message,
            "leverage": "Annonce déjà remise en ligne\u00a0: le vendeur peine peut-être à vendre." if reposts else None}


def detail(store: Store, row, j: Judgement, saved: bool, viewer: Viewer | None = None,
           user_id: str | None = None) -> dict:
    appr = _appraisal(row)
    raw = _raw(row)
    out = card(row, j)
    out.update({
        "url": row["url"],
        "images": (raw.get("image_urls") or [])[:10],
        "description": (raw.get("description") or "")[:2000],
        "condition": row["condition"],
        "department": row["department"],
        "method": appr.get("method"),
        "parts": [
            {"label": b.get("label") or b.get("key"), "qty": b.get("qty", 1),
             "value": _r(b.get("value")), "source": b.get("source"), "n": b.get("n", 0),
             "condition": b.get("condition", "working"), "days_to_sell": b.get("days_to_sell")}
            for b in appr.get("breakdown") or []
        ],
        "floor": _r(appr.get("floor")),
        "floor_net": _r(appr["floor"] - row["price"] - j.logistics)
        if appr.get("floor") is not None and j.logistics is not None else None,
        "negotiation": negotiation(row, j, viewer) if viewer else None,
        "feedback": store.feedback_summary(row["uid"], user_id),
        "photo_checked": bool(appr.get("photo_checked")),
        "shippable": bool(appr.get("shippable", True)),
        "scam_score": appr.get("risk"),
        "seller": appr.get("seller"),
        "reasons": list(j.decision.reasons),
        "price_history": [{"price": p["price"], "at": p["seen_at"]} for p in store.price_points(row["uid"])],
        "saved": saved,
    })
    return out


def teaser(store: Store, viewer: Viewer | None, max_age_days: int) -> dict:
    """What a non-subscriber may see: proof the product works near them,
    nothing they could act on (no title, link, price or position)."""
    if viewer is None:
        return {"count": 0, "best_net": None, "near": 0, "by_category": {}}
    items = deals_for(store, viewer, max_age_days)
    by_cat: dict[str, int] = {}
    for row, _ in items:
        by_cat[row["category"] or "other"] = by_cat.get(row["category"] or "other", 0) + 1
    best = max((j.net or 0 for _, j in items), default=None)
    return {
        "count": len(items),
        "best_net": int(best // 10 * 10) if best else None,   # coarse on purpose
        "near": sum(1 for _, j in items if j.mode == "pickup"),
        "by_category": by_cat,
    }
