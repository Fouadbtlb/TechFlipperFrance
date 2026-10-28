"""After each scan cycle: push every subscriber the new deals that are deals
FOR THEM (their home, their bar, their categories), once each.

Notification fatigue is the main reason people turn pushes off or uninstall,
so every push has to be worth it:
- one message per user per cycle, bundling a burst into a single summary;
- quiet hours (no buzzing at night): deals found then arrive as a morning
  digest, because "not yet notified" deals stay eligible for NOTIFY_WINDOW;
- a daily ceiling per user.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from ..config import Settings
from ..notify.push import ExpoPush
from ..storage import Store
from .accounts import Accounts
from .deals import deals_for, viewer_for

log = logging.getLogger(__name__)

PARIS = ZoneInfo("Europe/Paris")
QUIET_START = time(22, 0)
QUIET_END = time(8, 0)
MAX_PER_DAY = 8
# A deal first seen longer ago than this is no longer news: never pushed.
NOTIFY_WINDOW = timedelta(hours=12)
NBSP = " "


def in_quiet_hours(now: datetime) -> bool:
    t = now.astimezone(PARIS).time()
    return t >= QUIET_START or t < QUIET_END


class PushFanout:
    def __init__(self, settings: Settings, max_age_days: int = 7, push: ExpoPush | None = None,
                 clock=lambda: datetime.now(timezone.utc)):
        self.settings = settings
        self.max_age_days = max_age_days
        self.push = push or ExpoPush()
        self.clock = clock

    def __call__(self, uids: list[str] | None = None) -> int:
        """`uids` (this cycle's fresh deals) is only a hint: every recent deal
        not yet pushed is considered, so a night or a failed cycle loses nothing."""
        now = self.clock()
        if in_quiet_hours(now):
            return 0
        store = Store(self.settings.db_path)
        accounts = Accounts(self.settings.db_path)
        try:
            return self._run(store, accounts, now)
        finally:
            store.conn.close()
            accounts.close()

    def _run(self, store: Store, accounts: Accounts, now: datetime) -> int:
        cutoff = (now - NOTIFY_WINDOW).isoformat()
        messages, plan = [], []
        for user in accounts.push_audience():
            viewer = viewer_for(user, self.settings)
            if viewer is None or accounts.usage_today(user["id"], "push") >= MAX_PER_DAY:
                continue
            items = [(r, j) for r, j in deals_for(store, viewer, self.max_age_days,
                                                  hidden=accounts.hidden_uids(user["id"]))
                     if (r["first_seen"] or "") >= cutoff]
            seen = accounts.notified_uids(user["id"], [r["uid"] for r, _ in items])
            fresh = sorted(((r, j) for r, j in items if r["uid"] not in seen),
                           key=lambda it: -(it[1].net or 0))
            if not fresh:
                continue
            messages.append(_message(user["push_token"], fresh))
            plan.append((user["id"], [r["uid"] for r, _ in fresh]))
        if not messages:
            return 0
        for token in self.push.send(messages):
            accounts.clear_push_token(token)
        for user_id, sent in plan:
            accounts.mark_notified(user_id, sent)
            accounts.bump_usage(user_id, "push")
        log.info("push: %d subscriber(s) notified", len(messages))
        return len(messages)


def _eur(x: float) -> str:
    return f"{x:,.0f}".replace(",", NBSP) + f"{NBSP}€"


def _message(token: str, fresh) -> dict:
    row, j = fresh[0]
    where = f"à {j.distance_km:.0f}{NBSP}km" if j.mode == "pickup" and j.distance_km is not None \
        else "avec envoi"
    if len(fresh) == 1:
        title = f"+{_eur(j.net)} · {row['title'][:48]}"
        body = f"{_eur(row['price'])}, revente estimée {_eur(row['true_value'])}, {where}"
        data = {"uid": row["uid"]}
    else:
        title = f"{len(fresh)} nouvelles affaires pour toi"
        body = f"Jusqu’à +{_eur(j.net)} : {row['title'][:40]}, {where}"
        data = {"screen": "feed"}
    return {"to": token, "title": title, "body": body, "data": data, "sound": "default",
            "channelId": "deals"}
