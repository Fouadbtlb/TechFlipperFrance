"""After each scan cycle: push every subscriber the new deals that are deals
FOR THEM (their home, their bar, their categories), once each, at most a few
per cycle so a burst never turns into spam."""
from __future__ import annotations

import logging

from ..config import Settings
from ..notify.push import ExpoPush
from ..storage import Store
from .accounts import Accounts
from .deals import deals_for, viewer_for

log = logging.getLogger(__name__)

MAX_PER_CYCLE = 3


class PushFanout:
    def __init__(self, settings: Settings, max_age_days: int = 7, push: ExpoPush | None = None):
        self.settings = settings
        self.max_age_days = max_age_days
        self.push = push or ExpoPush()

    def __call__(self, uids: list[str]) -> int:
        store = Store(self.settings.db_path)
        accounts = Accounts(self.settings.db_path)
        try:
            return self._run(store, accounts, uids)
        finally:
            store.conn.close()
            accounts.close()

    def _run(self, store: Store, accounts: Accounts, uids: list[str]) -> int:
        messages, plan = [], []
        for user in accounts.push_audience():
            viewer = viewer_for(user, self.settings)
            if viewer is None:
                continue
            items = deals_for(store, viewer, self.max_age_days,
                              hidden=accounts.hidden_uids(user["id"]), uids=uids)
            seen = accounts.notified_uids(user["id"], [r["uid"] for r, _ in items])
            fresh = sorted(((r, j) for r, j in items if r["uid"] not in seen),
                           key=lambda it: -(it[1].net or 0))
            if not fresh:
                continue
            messages.append(_message(user["push_token"], fresh[:MAX_PER_CYCLE], len(fresh)))
            plan.append((user["id"], [r["uid"] for r, _ in fresh]))
        if not messages:
            return 0
        for token in self.push.send(messages):
            accounts.clear_push_token(token)
        for user_id, sent in plan:
            accounts.mark_notified(user_id, sent)
        log.info("push: %d subscriber(s) notified", len(messages))
        return len(messages)


def _message(token: str, top, total: int) -> dict:
    row, j = top[0]
    where = f"{j.distance_km:.0f} km" if j.distance_km is not None else "envoi"
    if total == 1:
        title = f"+{j.net:.0f} € · {row['title'][:48]}"
        body = f"{row['price']:.0f} € · revente ~{row['true_value']:.0f} € · {where}"
        data = {"uid": row["uid"]}
    else:
        title = f"{total} nouvelles affaires pour toi"
        body = f"Jusqu'à +{j.net:.0f} € · {row['title'][:40]} · {where}"
        data = {"uid": row["uid"], "screen": "feed"}
    return {"to": token, "title": title, "body": body, "data": data, "sound": "default",
            "channelId": "deals"}
