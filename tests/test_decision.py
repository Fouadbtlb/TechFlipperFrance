from techflip.decision import decide, default_policy

P = default_policy()


def test_easy_alerts_on_thin_margin_and_low_confidence():
    d = decide(true_value=200, price=150, logistics=10, zone="EASY", confidence=0.0, policy=P)
    assert d.alert and d.net_profit == 40.0


def test_medium_needs_bigger_margin():
    near_miss = decide(300, 240, 12, "MEDIUM", confidence=0.9, policy=P)
    assert not near_miss.alert  # net 48 < 80
    ok = decide(400, 300, 12, "MEDIUM", confidence=0.9, policy=P)
    assert ok.alert  # net 88 >= 80


def test_medium_needs_confidence():
    d = decide(400, 300, 12, "MEDIUM", confidence=0.3, policy=P)
    assert not d.alert  # margin fine but confidence below 0.4


def test_hard_high_bar_and_confidence():
    weak = decide(600, 480, 15, "HARD", confidence=0.9, policy=P)
    assert not weak.alert  # net 105 < 120
    strong = decide(700, 500, 15, "HARD", confidence=0.7, policy=P)
    assert strong.alert
    low_conf = decide(700, 500, 15, "HARD", confidence=0.5, policy=P)
    assert not low_conf.alert


def test_trade_and_inaccessible_are_dropped():
    assert not decide(500, 100, 10, "EASY", 1.0, P, is_trade=True).alert
    assert not decide(500, 100, None, "HARD", 1.0, P).alert


def test_far_scam_dropped_but_easy_scam_warned():
    far = decide(500, 200, 12, "HARD", 0.9, P, risk=7)
    assert not far.alert
    easy = decide(500, 200, 10, "EASY", 0.9, P, risk=7)
    assert easy.alert  # near enough to go check in person despite the flag
    hard_scam = decide(500, 200, 10, "EASY", 0.9, P, risk=9)
    assert not hard_scam.alert  # 8+ dropped everywhere


def test_implausible_value_vs_price_is_dropped():
    assert not decide(true_value=298, price=30, logistics=10, zone="EASY", confidence=0.9, policy=P).alert


def test_far_underpriced_is_scam_but_easy_bargain_is_kept():
    # HARD: a PS5 worth 400 listed at 150 ship-only = remote scam, dropped
    assert not decide(400, 150, 25, "HARD", 0.9, P).alert
    # EASY: same discount is a real bargain you can inspect and pay on pickup
    assert decide(400, 150, 10, "EASY", 0.9, P).alert
