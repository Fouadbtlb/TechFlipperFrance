import pytest


def _belgian_postcodes() -> bool:
    try:
        import pgeocode
        pgeocode.Nominatim("be")       # downloads and caches the table on first use
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def belgian_postcodes():
    """Cash Converters shops are placed through pgeocode's Belgian postcode
    table, downloaded once. Without network on first run, skip, not fail."""
    if not _belgian_postcodes():
        pytest.skip("pgeocode could not download the Belgian postcode table")
