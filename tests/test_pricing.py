from techflip.pricing.catalog import load_catalog
from techflip.pricing.extract import extract_components, primary_key, recognize
from techflip.pricing.tracker import PriceTracker
from techflip.pricing.appraise import appraise, build_items, Item

CATALOG = load_catalog("config/pricebook.yaml")


def keys(text):
    return {c.key for c in extract_components(text, CATALOG)}


def test_extract_finds_parts_inside_a_pc():
    k = keys("PC Gamer RTX 4070, Ryzen 5 5600, 16Go DDR4, alim 650W")
    assert "gpu:rtx-4070" in k
    assert "cpu:ryzen-5-5600" in k
    assert "ram:ddr4-16gb" in k
    assert "psu:650w" in k
    assert "gpu:rtx-4070-ti" not in k


def test_more_specific_variant_wins():
    assert keys("Carte graphique RTX 4070 Ti") == {"gpu:rtx-4070-ti"}
    assert keys("RTX 4070 Super neuve") == {"gpu:rtx-4070-super"}


def test_primary_key_only_for_single_item():
    assert primary_key(extract_components("RTX 3060 comme neuve", CATALOG)) == "gpu:rtx-3060"
    assert primary_key(extract_components("PC Gamer RTX 3060 + Ryzen 5 5600", CATALOG)) is None


def test_empty_text():
    assert extract_components("", CATALOG) == []


def rkeys(title, desc):
    return {c.key for c in recognize(title, desc, CATALOG)}


def test_recognize_trusts_title_gpu_over_description_noise():
    k = rkeys("PC Gamer RTX 4060", "equivalent RTX 3050, mieux qu'une GTX 1650 ou RTX 2060")
    assert "gpu:rtx-4060" in k
    assert "gpu:rtx-3050" not in k and "gpu:gtx-1650" not in k


def test_recognize_drops_ambiguous_description_only_gpus():
    k = rkeys("PC Gamer reconditionne", "RX 6600, GTX 1650, RTX 2060 ou RTX 3050 au choix")
    assert not any(x.startswith("gpu:") for x in k)


def test_recognize_keeps_single_description_component():
    k = rkeys("PC Gamer tour setup", "avec une RTX 3060 et un Ryzen 5 5600")
    assert "gpu:rtx-3060" in k and "cpu:ryzen-5-5600" in k


class FakeStore:
    def __init__(self, data):
        self.data = data

    def component_prices(self, key, since):
        return self.data.get(key, [])


def test_tracker_seed_when_no_data():
    t = PriceTracker(FakeStore({}), CATALOG, min_comparables=5)
    q = t.price("gpu:rtx-4070")
    assert q.source == "seed" and q.unit_value == 480 and q.n == 0


def test_tracker_learned_median_overrides_seed():
    store = FakeStore({"gpu:rtx-4070": [440, 450, 460, 455, 445, 470]})
    q = PriceTracker(store, CATALOG, min_comparables=5).price("gpu:rtx-4070")
    assert q.source == "learned" and q.n == 6 and q.unit_value == 452.5


def test_tracker_blends_below_threshold():
    store = FakeStore({"gpu:rtx-4070": [400, 420]})
    q = PriceTracker(store, CATALOG, min_comparables=5).price("gpu:rtx-4070")
    # w=2/5: 0.4*median(410) + 0.6*seed(480)
    assert q.source == "blend" and q.n == 2 and q.unit_value == 452.0


def test_tracker_unknown_key():
    q = PriceTracker(FakeStore({}), CATALOG).price("gpu:does-not-exist")
    assert q.source == "unknown" and q.unit_value is None


def test_tracker_drops_outliers_by_seed_band():
    store = FakeStore({"gpu:rtx-4070": [50, 460, 455, 450, 448, 452]})
    q = PriceTracker(store, CATALOG, min_comparables=5).price("gpu:rtx-4070")
    assert q.source == "learned" and q.n == 5 and q.unit_value == 452.0


class FixedTracker:
    def __init__(self, quotes):
        self.quotes = quotes

    def price(self, key):
        return self.quotes[key]


def _q(key, value, source, n=9):
    from techflip.pricing.tracker import PriceQuote
    return PriceQuote(key, value, source, n)


def test_appraise_sums_with_realization_and_confidence():
    tracker = FixedTracker({
        "gpu:rtx-4070": _q("gpu:rtx-4070", 450, "learned"),
        "cpu:ryzen-5-5600": _q("cpu:ryzen-5-5600", 100, "seed", 0),
    })
    items = [Item("gpu:rtx-4070", 1, "working", "RTX 4070"),
             Item("cpu:ryzen-5-5600", 1, "working", "Ryzen 5 5600")]
    a = appraise(items, tracker, realization_factor=0.85)
    assert a.gross_value == 550.0
    assert a.true_value == 467.5
    assert a.confidence == round(450 / 550, 2)
    assert a.n_priced == 2 and a.n_unpriced == 0


def test_appraise_applies_per_category_realization():
    tracker = FixedTracker({
        "gpu:rtx-4070": _q("gpu:rtx-4070", 400, "learned"),
        "psu:650w": _q("psu:650w", 100, "learned"),
    })
    items = [Item("gpu:rtx-4070", 1, "working", "RTX 4070", "gpu"),
             Item("psu:650w", 1, "working", "650W", "psu")]
    a = appraise(items, tracker)
    assert a.gross_value == 500.0
    # gpu 0.85, psu 0.70 -> 340 + 70, not a flat 0.85 (which would be 425)
    assert a.true_value == 410.0


def test_appraise_counts_unpriced():
    tracker = FixedTracker({"laptop:x": _q("laptop:x", None, "unknown", 0)})
    a = appraise([Item("laptop:x", 1, "working", "Laptop")], tracker)
    assert a.n_priced == 0 and a.n_unpriced == 1 and a.true_value == 0.0


def test_build_items_merges_llm_extras_and_condition():
    text = extract_components("Lot Xbox Series S", CATALOG)
    llm = {"condition": "working", "extra_controllers": 2,
           "extra_storage": "SSD 1To", "notable_games": ["FIFA", "GTA"]}
    items = build_items(text, llm, CATALOG)
    by_key = {i.key: i for i in items}
    assert "console:xbox-series-s" in by_key
    assert by_key["controller:xbox"].qty == 2
    assert "game:standard" in by_key and by_key["game:standard"].qty == 2


def test_build_items_broken_downgrades_core_but_not_parts():
    text = extract_components("PC en panne RTX 3060", CATALOG)
    items = build_items(text, {"condition": "broken"}, CATALOG)
    gpu = next(i for i in items if i.key == "gpu:rtx-3060")
    assert gpu.condition == "unknown"


def test_recognize_console_must_be_in_title():
    k = rkeys("Manette DualSense Edge", "compatible PS5 et PC, comme neuve")
    assert not any(x.startswith("console:") for x in k)
    assert "controller:dualsense" in k


def test_recognize_console_in_title_kept():
    assert "console:ps5" in rkeys("PS5 edition standard + manette", "")


def test_recognize_single_item_ignores_description_parts():
    k = rkeys("Rtx 4070 videokaart", "zat in een pc met Ryzen 7 5800X en 32Go DDR4")
    assert k == {"gpu:rtx-4070"}


def test_recognize_bundle_absorbs_description_parts():
    k = rkeys("PC Gamer complet", "RTX 3060, Ryzen 5 5600, 16Go DDR4")
    assert {"gpu:rtx-3060", "cpu:ryzen-5-5600", "ram:ddr4-16gb"} <= k


def test_console_dropped_when_accessory_leads():
    assert not any(x.startswith("console:") for x in rkeys("Manette PS5 DualSense", ""))
    assert rkeys("Support PS5", "") == set()


def test_console_kept_when_it_leads():
    assert "console:ps5" in rkeys("PS5 slim + manette", "")


def test_tracker_rejects_bundle_priced_outliers():
    store = FakeStore({"gpu:rtx-4070": [420, 450, 470, 455, 445, 1300, 1400]})
    q = PriceTracker(store, CATALOG, min_comparables=5).price("gpu:rtx-4070")
    assert q.unit_value == 450.0 and q.n == 5 and q.source == "learned"


def test_build_items_detects_broken_from_text():
    text = extract_components("PS5 HS ne s'allume plus", CATALOG)
    items = build_items(text, None, CATALOG, "PS5 HS ne s'allume plus")
    ps5 = next(i for i in items if i.key == "console:ps5")
    assert ps5.condition == "broken"


def test_classification_maps_types_not_ambiguous_text():
    from techflip.pricing.appraise import items_from_classification
    v = {"type": "controller", "condition": "working",
         "components": [{"type": "controller", "model": "Manette PS5 DualSense", "qty": 2}]}
    items = items_from_classification(v, CATALOG)
    assert {i.key for i in items} == {"controller:dualsense"}
    assert items[0].qty == 2


def test_classification_builds_pc_parts():
    from techflip.pricing.appraise import items_from_classification
    v = {"type": "pc", "condition": "working", "components": [
        {"type": "gpu", "model": "RTX 4070", "qty": 1},
        {"type": "cpu", "model": "Ryzen 5 5600", "qty": 1},
        {"type": "ram", "model": "16Go DDR4", "qty": 1}]}
    assert {i.key for i in items_from_classification(v, CATALOG)} == {"gpu:rtx-4070", "cpu:ryzen-5-5600", "ram:ddr4-16gb"}


def test_classification_uses_photo_model_over_title():
    from techflip.pricing.appraise import items_from_classification
    # title claimed PS5; the vision pass read a PS4 Slim off the photo
    v = {"type": "console", "condition": "working",
         "components": [{"type": "console", "model": "PS4 Slim", "qty": 1}]}
    items = items_from_classification(v, CATALOG)
    assert {i.key for i in items} == {"console:ps4-slim"}


def test_classification_empty_without_components():
    from techflip.pricing.appraise import items_from_classification
    assert items_from_classification({"type": "accessory", "components": []}, CATALOG) == []


def test_drifted_seeds_flags_a_stale_price_and_ignores_thin_evidence():
    """A seed the market disagrees with must surface, but only once enough
    single-item ads back the claim."""
    catalog = load_catalog("config/pricebook.yaml")
    store = _FakeStore({
        "gpu:rtx-3070": [300, 300, 310, 290, 300, 305],   # seed 320, ~-5% -> quiet
        "gpu:rtx-4090": [1100, 1150, 1120, 1130, 1140],   # seed 1500, -25% -> flag
        "gpu:rtx-3050": [90, 95],                         # too few samples -> quiet
    })
    tracker = PriceTracker(store, catalog, min_comparables=5, window_days=90)
    flagged = {r["key"]: r for r in tracker.drifted_seeds()}
    assert "gpu:rtx-4090" in flagged
    assert flagged["gpu:rtx-4090"]["market"] == 1130
    assert flagged["gpu:rtx-4090"]["drift"] < -0.2
    assert "gpu:rtx-3070" not in flagged
    assert "gpu:rtx-3050" not in flagged


class _FakeStore:
    def __init__(self, by_key):
        self.by_key = by_key

    def component_prices(self, key, since_iso):
        return self.by_key.get(key, [])
