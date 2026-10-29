import pytest


def _postcodes(*countries: str) -> bool:
    try:
        import pgeocode
        for cc in countries:
            pgeocode.Nominatim(cc)     # downloads and caches the table on first use
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def belgian_postcodes():
    """Cash Converters shops are placed through pgeocode's Belgian postcode
    table, downloaded once. Without network on first run, skip, not fail."""
    if not _postcodes("be"):
        pytest.skip("pgeocode could not download the Belgian postcode table")


@pytest.fixture(scope="session")
def postcodes():
    """The town lookup reads pgeocode's French and Belgian tables."""
    if not _postcodes("fr", "be"):
        pytest.skip("pgeocode could not download the French and Belgian postcode tables")
