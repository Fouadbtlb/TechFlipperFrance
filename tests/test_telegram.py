"""Delivery is the whole product: an alert that does not arrive did not happen.

A single "Connection reset by peer" to api.telegram.org was observed in normal
running, so one failed socket must not cost a deal.
"""
import urllib.error

import pytest

from techflip.notify import telegram as tg


class _Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _notifier():
    return tg.TelegramNotifier(token="t", chat_id="c")


def test_retries_a_transient_reset_then_succeeds(monkeypatch):
    calls = []

    def flaky(req, timeout=None):
        calls.append(1)
        if len(calls) < 3:
            raise urllib.error.URLError("[Errno 104] Connection reset by peer")
        return _Resp()

    monkeypatch.setattr(tg.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(tg.time, "sleep", lambda *a: None)
    assert _notifier().send_text("hi") is True
    assert len(calls) == 3


def test_gives_up_and_reports_failure(monkeypatch):
    def dead(req, timeout=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(tg.urllib.request, "urlopen", dead)
    monkeypatch.setattr(tg.time, "sleep", lambda *a: None)
    assert _notifier().send_text("hi") is False


def test_unconfigured_never_claims_delivery():
    assert tg.TelegramNotifier(token="", chat_id="").send_text("hi") is False


def test_success_does_not_retry(monkeypatch):
    calls = []
    monkeypatch.setattr(tg.urllib.request, "urlopen",
                        lambda req, timeout=None: (calls.append(1), _Resp())[1])
    monkeypatch.setattr(tg.time, "sleep", lambda *a: None)
    assert _notifier().send_text("hi") is True
    assert len(calls) == 1
