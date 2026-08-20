"""Telegram alerts via the raw Bot API (stdlib urllib — zero extra deps).

Setup (one-time, free):
1. Talk to @BotFather on Telegram → /newbot → copy the token
2. Send any message to your bot, then open
   https://api.telegram.org/bot<TOKEN>/getUpdates → read your chat id
3. Put both in .env
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request

from ..domain import Listing, ScoreResult




log = logging.getLogger(__name__)

_ATTEMPTS = 3
_BACKOFF = 2.0


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send_deal(
        self, l: Listing, s: ScoreResult, extra_lines: list[str] | tuple = ()
    ) -> bool:
        """True only if Telegram accepted the message. The caller writes the
        deal off on this answer, so a silent failure loses it for good."""
        return self._send(self._format(l, s, extra_lines))

    def send_text(self, text: str) -> bool:
        return self._send(text)

    # ----------

    def _format(
        self, l: Listing, s: ScoreResult, extra_lines: list[str] | tuple = ()
    ) -> str:
        """Compact alert: 4-6 lines for a tech bundle deal."""
        loc = ", ".join(x for x in (l.city, l.department) if x) or "?"
        badge = "🎯"

        lines = [
            f"{badge} <b>PROFIT: +{s.net_profit:,.0f}€</b> — {_esc(l.title[:55])}",
            f"<b>{l.price:,.0f} €</b> · Revente estimée {s.true_value:,.0f} €".replace(",", " "),
            f"{l.condition or '?'} · {loc}",
        ]

        lines += [f"{_esc(r)}" for r in s.reasons if r[:2] in ("🚩", "⚠️")]

        for x in extra_lines:
            if not x or x[:1] in (" ", "—") or x.lstrip()[:1] == "·":
                continue
            lines.append(_esc(x if len(x) <= 78 else x[:77] + "…"))

        link = f'<a href="{l.url}">🔗 Lier Leboncoin</a>'
        lines.append(link)
        return "\n".join(lines)

    def _send(self, text: str) -> bool:
        if not self.enabled:
            log.warning("Telegram not configured; message:\n%s", text)
            return False
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = json.dumps({
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        # api.telegram.org resets a connection now and then. One dropped socket
        # must not cost a deal, so retry briefly before reporting failure.
        for attempt in range(_ATTEMPTS):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status != 200:
                        log.error("Telegram HTTP %s", resp.status)
                        return False
                    return True
            except Exception:
                last = attempt == _ATTEMPTS - 1
                log.warning("Telegram send failed (try %d/%d)%s",
                            attempt + 1, _ATTEMPTS, "" if last else ", retrying",
                            exc_info=last)
                if not last:
                    time.sleep(_BACKOFF * (attempt + 1))
        return False


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
