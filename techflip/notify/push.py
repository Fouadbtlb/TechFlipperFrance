"""Expo push notifications (the app's alert channel; Telegram stays for the owner).

Endpoint and the 100-messages-per-request chunk come from Expo's own
expo-server-sdk. An optional access token enables Expo's "enhanced push
security", so a leaked device token alone cannot be used to spam users.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

SEND_URL = "https://exp.host/--/api/v2/push/send"
CHUNK = 100


def is_expo_token(token: str) -> bool:
    return isinstance(token, str) and (
        token.startswith("ExponentPushToken[") or token.startswith("ExpoPushToken[")
    ) and token.endswith("]") and len(token) < 200


class ExpoPush:
    def __init__(self, access_token: str = "", http: httpx.Client | None = None):
        self.access_token = access_token
        self.http = http or httpx.Client(timeout=15)

    def send(self, messages: list[dict]) -> list[str]:
        """Send messages ({to, title, body, data}). Returns device tokens Expo
        reports as no longer registered, so the caller can forget them."""
        dead: list[str] = []
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        for i in range(0, len(messages), CHUNK):
            chunk = messages[i:i + CHUNK]
            try:
                r = self.http.post(SEND_URL, json=chunk, headers=headers)
                r.raise_for_status()
                tickets = r.json().get("data") or []
            except Exception:
                log.warning("Expo push failed for %d message(s)", len(chunk), exc_info=True)
                continue
            # Expo answers one ticket per message, in order.
            for msg, t in zip(chunk, tickets, strict=False):
                if t.get("status") == "error" and \
                        (t.get("details") or {}).get("error") == "DeviceNotRegistered":
                    dead.append(msg["to"])
        return dead
