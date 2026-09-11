"""Leboncoin source, backed by the unofficial `lbc` client (curl-cffi).

Anti-detection posture (re-tested live 2026-08-12):
- The lbc client sends a Leboncoin MOBILE APP user-agent, so the TLS fingerprint
  must match a mobile stack. WHICH mobile stack passes is not stable: on
  2026-08-12 every safari*_ios fingerprint drew an instant DataDome 403 and
  "chrome_android" was the one that got through, the reverse of the posture
  that held on 2026-07-20. Re-test rather than trusting this note.
- ONE consistent fingerprint per process (rotating looks robotic)
- max_retries=1: retry storms make DataDome flag the IP harder; real backoff
  lives in the pipeline
- newest-first sort so page 1 is always enough
"""
from __future__ import annotations

import logging

import lbc

from ..config import SearchConfig
from ..domain import Listing, SellerInfo

log = logging.getLogger(__name__)




class LeboncoinSource:
    name = "leboncoin"

    def __init__(self, proxy: str | None = None, impersonate: str = "safari_ios"):
        self.client = lbc.Client(impersonate=impersonate, max_retries=1)
        if proxy:
            self.client.session.proxies = {"http": proxy, "https": proxy}

    def fetch(self, search: SearchConfig, page: int = 1) -> list[Listing]:
        result = self.client.search(
            url=search.url,
            sort=lbc.Sort.NEWEST,
            limit=35,
            page=page,
        )
        listings = []
        for ad in result.ads:
            if getattr(ad, "status", "active") != "active":
                continue
            title = (ad.subject or "").lower()
            if any(k in title for k in ["vendu", "réservé", "reserve", "achat en cours"]):
                continue
                
            try:
                listings.append(self._normalize(ad, search.name))
            except Exception:
                log.exception("Failed to normalize ad %s", getattr(ad, "id", "?"))
        return listings

    def fetch_seller(self, seller_id: str) -> SellerInfo | None:
        """One extra request. Call only for listings that scored as deals."""
        try:
            u = self.client.get_user(user_id=seller_id)
        except Exception:
            log.warning("Seller fetch failed for %s", seller_id, exc_info=True)
            return None
        fb = u.feedback
        return SellerInfo(
            seller_id=seller_id,
            name=u.name,
            account_type=u.account_type,
            registered_at=u.registered_at,
            total_ads=u.total_ads,
            feedback_score=fb.score if fb else None,
            feedback_count=int(fb.received_count) if fb and fb.received_count else None,
        )

    # ---------- normalization ----------

    def _normalize(self, ad, search_name: str) -> Listing:
        attrs = ad.attributes or {}

        def attr_label(key: str) -> str | None:
            a = attrs.get(key)
            return (a.value_label or a.value) if a else None

        return Listing(
            source=self.name,
            source_id=str(ad.id),
            url=ad.url,
            title=ad.subject or "",
            price=ad.price,
            published_at=ad.first_publication_date,
            brand=attr_label("brand"),
            model=attr_label("model"),
            condition=attr_label("etat") or attr_label("condition") or None,
            description=ad.body or "",
            city=ad.location.city if ad.location else None,
            zipcode=ad.location.zipcode if ad.location else None,
            department=ad.location.department_name if ad.location else None,
            country="FR",
            owner_type=None,
            has_phone=bool(ad.has_phone),
            seller_id=str(getattr(ad, "_user_id", "") or "") or None,
            image_urls=tuple(ad.images or []),
            search_name=search_name,
        )
