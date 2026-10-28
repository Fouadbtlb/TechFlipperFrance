"""Deals, computed for the caller: feed, map, detail, feedback, saved, hidden.

Everything here is behind the paywall except the teaser, which only reveals
counts (nothing a non-subscriber could act on).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from ... import tuning
from ...viewer import judge
from ..deals import (
    BUCKETS,
    CATEGORIES,
    SORTS,
    card,
    deals_for,
    detail,
    is_reliable,
    pin,
    sort_deals,
    teaser,
    viewer_for,
)
from ..deps import (
    NOT_FOUND,
    AccountsDep,
    CurrentUser,
    PaidUser,
    ServicesDep,
    StoreDep,
    ThrottledUser,
    ViewerDep,
    api_error,
)
from ..schemas import FeedbackIn, HideIn

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["deals"])


@router.get("/teaser")
def get_teaser(user: CurrentUser, store: StoreDep, svc: ServicesDep):
    return teaser(store, viewer_for(user, svc.settings), svc.api.deals_max_age_days)


@router.get("/deals")
def list_deals(user: ThrottledUser, viewer: ViewerDep, store: StoreDep, accounts: AccountsDep, svc: ServicesDep,
               sort: str = Query("profit"), category: str | None = Query(None), bucket: str = Query("reliable"),
               limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0, le=5000)):
    if sort not in SORTS or bucket not in BUCKETS or (category and category not in CATEGORIES):
        raise api_error(400, "bad_query")
    every = deals_for(store, viewer, svc.api.deals_max_age_days, hidden=accounts.hidden_uids(user["id"]),
                      category=category)
    reliable = [it for it in every if is_reliable(it[0])]
    chosen = reliable if bucket == "reliable" else [it for it in every if not is_reliable(it[0])]
    items = sort_deals(chosen, sort)
    page = items[offset:offset + limit]
    return {
        "total": len(items),
        "items": [card(r, j) for r, j in page],
        "counts": {"reliable": len(reliable), "check": len(every) - len(reliable)},
        "next_offset": offset + limit if offset + limit < len(items) else None,
    }


@router.get("/deals/map")
def map_pins(user: ThrottledUser, viewer: ViewerDep, store: StoreDep, accounts: AccountsDep, svc: ServicesDep):
    items = deals_for(store, viewer, svc.api.deals_max_age_days, hidden=accounts.hidden_uids(user["id"]))
    # The best 250 are plenty on a phone screen and keep the payload small.
    items = [it for it in sort_deals(items, "profit") if it[0]["lat"] is not None][:tuning.MAP_MAX_PINS]
    return {"items": [dict(pin(r, j), card=card(r, j)) for r, j in items]}


@router.get("/deals/{uid:path}")
def get_deal(uid: str, user: ThrottledUser, viewer: ViewerDep, store: StoreDep, accounts: AccountsDep,
             svc: ServicesDep):
    if accounts.bump_usage(user["id"], "detail") > svc.api.detail_views_per_day:
        log.warning("detail ceiling hit by %s", user["id"])
        raise api_error(429, "daily_limit",
                        "Tu as consulté beaucoup de fiches aujourd’hui. La limite se réinitialise demain.")
    row = _appraised(store, uid)
    return detail(store, row, judge(row, viewer), uid in accounts.saved_uids(user["id"]),
                  viewer=viewer, user_id=user["id"])


@router.post("/deals/{uid:path}/feedback")
def feedback(uid: str, body: FeedbackIn, user: PaidUser, store: StoreDep):
    """One voice per subscriber and listing (a new vote replaces the old). The
    tracker only moves an estimate once several people agree, within bounds
    (see tuning.FEEDBACK_*)."""
    row = _appraised(store, uid)
    if body.verdict is None and body.resale_price is None:
        raise api_error(400, "empty_feedback")
    low, high = tuning.RESALE_PLAUSIBLE
    if body.resale_price is not None and row["true_value"] and \
            not low * row["true_value"] <= body.resale_price <= high * row["true_value"]:
        raise api_error(400, "implausible_price", "Ce prix semble très éloigné de la valeur de l’objet.")
    store.add_feedback(user["id"], uid, body.verdict, body.resale_price)
    return store.feedback_summary(uid, user["id"])


@router.get("/saved")
def saved(user: ThrottledUser, viewer: ViewerDep, store: StoreDep, accounts: AccountsDep):
    out = []
    for uid in accounts.saved_uids(user["id"]):
        row = store.get(uid)
        if row is None or not row["appraisal"]:
            continue
        out.append(dict(card(row, judge(row, viewer)), gone=row["status"] != "active"))
    return {"items": out}


@router.put("/saved/{uid:path}")
def save(uid: str, user: PaidUser, store: StoreDep, accounts: AccountsDep):
    _exists(store, uid)
    accounts.save(user["id"], uid)
    return {"ok": True}


@router.delete("/saved/{uid:path}")
def unsave(uid: str, user: PaidUser, accounts: AccountsDep):
    accounts.unsave(user["id"], uid)
    return {"ok": True}


@router.post("/hidden/{uid:path}")
def hide(uid: str, body: HideIn, user: PaidUser, store: StoreDep, accounts: AccountsDep):
    _exists(store, uid)
    if accounts.hide(user["id"], uid, body.reason) >= 2:
        store.mark_gone(uid)  # two independent "vendu" reports: gone for everyone
    return {"ok": True}


def _exists(store, uid: str):
    row = store.get(uid)
    if row is None:
        raise api_error(404, "not_found", NOT_FOUND)
    return row


def _appraised(store, uid: str):
    row = _exists(store, uid)
    if not row["appraisal"]:
        raise api_error(404, "not_found", NOT_FOUND)
    return row
