"""After each scan cycle: push every subscriber the new deals that are deals
FOR THEM (their home, their bar, their categories), once each.

Notification fatigue is the main reason people turn pushes off or uninstall,
so every push has to be worth it:
- one message per user per cycle, bundling a burst into a single summary;
- quiet hours (no buzzing at night): deals found then arrive as a morning
  digest, because "not yet notified" deals stay eligible for NOTIFY_WINDOW;
- a daily ceiling per user;
- only "reliable" deals: the uncertain ones wait in the "À vérifier" tab;
- or, for people who prefer calm, one evening summary a day ("daily").
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .. import tuning
from ..config import Settings
from ..notify.push import ExpoPush
from ..storage import Store
from .accounts import Accounts
from .deals import deals_for, viewer_for

log = logging.getLogger(__name__)

PARIS = ZoneInfo("Europe/Paris")
QUIET_START, QUIET_END = tuning.QUIET_START, tuning.QUIET_END
MAX_PER_DAY = tuning.MAX_PUSHES_PER_DAY
NOTIFY_WINDOW, DIGEST_WINDOW = tuning.NOTIFY_WINDOW, tuning.DIGEST_WINDOW
DIGEST_HOUR = tuning.DIGEST_HOUR
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
        self._pruned_on = None

    def __call__(self, uids: list[str] | None = None) -> int:
        """`uids` (this cycle's fresh deals) is only a hint: every recent deal
        not yet pushed is considered, so a night or a failed cycle loses nothing."""
        now = self.clock()
        if in_quiet_hours(now):
            return 0
        store = Store(self.settings.db_path)
        accounts = Accounts(self.settings.db_path)
        try:
            if self._pruned_on != now.date():
                accounts.prune()
                self._pruned_on = now.date()
            return self._run(store, accounts, now)
        finally:
            store.close()
            accounts.close()

    def _run(self, store: Store, accounts: Accounts, now: datetime) -> int:
        messages, plan = [], []
        paris_hour = now.astimezone(PARIS).hour
        for user in accounts.push_audience():
            viewer = viewer_for(user, self.settings)
            sent_today = accounts.usage_today(user["id"], "push")
            if viewer is None or sent_today >= MAX_PER_DAY:
                continue
            daily = (user["notify_mode"] or "instant") == "daily"
            if daily and (paris_hour < DIGEST_HOUR or sent_today > 0):
                continue
            cutoff = (now - (DIGEST_WINDOW if daily else NOTIFY_WINDOW)).isoformat()
            items = [(r, j) for r, j in deals_for(store, viewer, self.max_age_days,
                                                  hidden=accounts.hidden_uids(user["id"]),
                                                  bucket="reliable")
                     if (r["first_seen"] or "") >= cutoff]
            seen = accounts.notified_uids(user["id"], [r["uid"] for r, _ in items])
            fresh = sorted(((r, j) for r, j in items if r["uid"] not in seen),
                           key=lambda it: -(it[1].net or 0))
            if not fresh:
                continue
            messages.append(_message(user["push_token"], fresh, daily))
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


def _message(token: str, fresh, daily: bool = False) -> dict:
    row, j = fresh[0]
    where = f"à {j.distance_km:.0f}{NBSP}km" if j.mode == "pickup" and j.distance_km is not None \
        else "avec envoi"
    if daily:
        title = f"Le relevé du jour : {len(fresh)} affaire{'s' if len(fresh) > 1 else ''} pour toi"
        body = f"La meilleure : +{_eur(j.net)}, {row['title'][:40]}, {where}"
        data = {"screen": "feed"}
    elif len(fresh) == 1:
        title = f"+{_eur(j.net)} · {row['title'][:48]}"
        body = f"{_eur(row['price'])}, revente estimée {_eur(row['true_value'])}, {where}"
        data = {"uid": row["uid"]}
    else:
        title = f"{len(fresh)} nouvelles affaires pour toi"
        body = f"Jusqu’à +{_eur(j.net)} : {row['title'][:40]}, {where}"
        data = {"screen": "feed"}
    return {"to": token, "title": title, "body": body, "data": data, "sound": "default",
            "channelId": "deals"}
