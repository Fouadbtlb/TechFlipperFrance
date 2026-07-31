"""Distance to Lille, zone classification, and logistics cost.

Postal code to lat/lng uses pgeocode when installed (GeoNames data, cached after
first use); otherwise it falls back to a small bundled anchor table and returns
None for anything it does not know. An unknown distance is treated as far (HARD),
which is the conservative choice.
"""
from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

LILLE = (50.6292, 3.0573)

SHIPPING_COSTS = {"bulky": 25.0, "parcel": 12.0, "small": 6.0, "default": 12.0}

# Coarse offline fallback: enough Hauts-de-France points to zone the near ring,
# plus a few far cities. pgeocode supersedes this when available.
_ANCHORS = {
    "59000": (50.6292, 3.0573),  # Lille
    "59200": (50.6942, 3.1746),  # Tourcoing
    "59100": (50.6907, 3.1560),  # Roubaix
    "59300": (50.3597, 3.5233),  # Valenciennes
    "59140": (51.0347, 2.3770),  # Dunkerque
    "62000": (50.2910, 2.7772),  # Arras
    "62300": (50.4300, 2.8300),  # Lens
    "80000": (49.8941, 2.2957),  # Amiens
    "02100": (49.8400, 3.2870),  # Saint-Quentin
    "60000": (49.4180, 2.8260),  # Beauvais
    "76000": (49.4432, 1.0993),  # Rouen
    "75001": (48.8600, 2.3400),  # Paris
    "69001": (45.7700, 4.8300),  # Lyon
    "13001": (43.3000, 5.3800),  # Marseille
    "33000": (44.8400, -0.5800),  # Bordeaux
    "06000": (43.7000, 7.2500),  # Nice
    "67000": (48.5830, 7.7450),  # Strasbourg
}


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return r * 2 * asin(sqrt(a))


def zone_for_distance(distance_km: float | None, easy_km: float = 60, medium_km: float = 150) -> str:
    if distance_km is None:
        return "HARD"
    if distance_km <= easy_km:
        return "EASY"
    if distance_km <= medium_km:
        return "MEDIUM"
    return "HARD"


def logistics_cost(
    distance_km: float | None,
    ship_class: str = "parcel",
    shippable: bool = True,
    cost_per_km: float = 0.25,
    shipping_costs: dict | None = None,
) -> float | None:
    """Cheapest of driving round-trip or shipping. None if neither is possible."""
    shipping_costs = shipping_costs or SHIPPING_COSTS
    options = []
    if distance_km is not None:
        options.append(2 * distance_km * cost_per_km)
    if shippable:
        options.append(shipping_costs.get(ship_class, shipping_costs["default"]))
    if not options:
        return None
    return round(min(options), 2)


class Locator:
    def __init__(self, resolver=None):
        self._resolver = resolver or _default_resolver()

    def latlng(self, zipcode: str | None) -> tuple[float, float] | None:
        if not zipcode:
            return None
        return self._resolver(str(zipcode).strip()[:5])

    def distance(self, zipcode=None, lat=None, lng=None) -> float | None:
        if lat is not None and lng is not None:
            d = round(haversine(LILLE[0], LILLE[1], lat, lng), 1)
            return d if d <= 2000 else None
        return self.distance_to_lille(zipcode)

    def distance_to_lille(self, zipcode: str | None) -> float | None:
        ll = self.latlng(zipcode)
        if ll is None:
            return None
        return round(haversine(LILLE[0], LILLE[1], ll[0], ll[1]), 1)


def _default_resolver():
    pg = _pgeocode_resolver()

    def resolve(z: str):
        if pg:
            hit = pg(z)
            if hit:
                return hit
        return _ANCHORS.get(z)

    return resolve


def _pgeocode_resolver():
    try:
        import pgeocode
    except Exception:
        return None
    nomi = pgeocode.Nominatim("fr")

    def query(z: str):
        r = nomi.query_postal_code(z)
        lat, lon = r["latitude"], r["longitude"]
        if lat != lat or lon != lon:  # NaN when unknown
            return None
        return (float(lat), float(lon))

    return query
