"""2ememain publishes a human date ("Hier", "6 aout 26"), not a timestamp.

It was dropped on the floor, so every Belgian listing landed with published_at
NULL and the resweep -- which filters on published_at -- could never revisit one.
A listing that failed to alert on the cycle it first appeared was lost for good.
"""
import datetime as dt

from techflip.sources.deuxememain import _published_at

TODAY = dt.date(2026, 8, 12)


def test_relative_days_french_and_dutch():
    assert _published_at("Aujourd'hui", TODAY) == "2026-08-12"
    assert _published_at("Vandaag", TODAY) == "2026-08-12"
    assert _published_at("Hier", TODAY) == "2026-08-11"
    assert _published_at("Gisteren", TODAY) == "2026-08-11"
    assert _published_at("Avant-hier", TODAY) == "2026-08-10"
    assert _published_at("Eergisteren", TODAY) == "2026-08-10"


def test_absolute_dates():
    assert _published_at("6 août 26", TODAY) == "2026-08-06"
    assert _published_at("5 aout 26", TODAY) == "2026-08-05"
    assert _published_at("31 juillet 26", TODAY) == "2026-07-31"
    assert _published_at("1 jan 26", TODAY) == "2026-01-01"
    assert _published_at("28 aug 25", TODAY) == "2025-08-28"


def test_a_bare_time_means_today():
    assert _published_at("10:23", TODAY) == "2026-08-12"


def test_unparseable_stays_none_rather_than_lying():
    assert _published_at("", TODAY) is None
    assert _published_at(None, TODAY) is None
    assert _published_at("bientôt", TODAY) is None


def test_result_is_comparable_with_the_resweep_cutoff():
    since = (TODAY - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    assert _published_at("Hier", TODAY) >= since
    assert _published_at("31 juillet 26", TODAY) < since
