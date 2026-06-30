"""Live CrossRef metadata tests (network)."""

import pytest

from doi_pdf import crossref_metadata

pytestmark = pytest.mark.network


def test_crossref_metadata_returns_record_for_known_doi() -> None:
    meta = crossref_metadata("10.1371/journal.pone.0234245")
    assert isinstance(meta, dict)
    # CrossRef echoes the DOI back (case-insensitively).
    assert meta["DOI"].lower() == "10.1371/journal.pone.0234245"
    assert meta.get("title")  # non-empty title list/string


def test_crossref_metadata_accepts_url_form() -> None:
    meta = crossref_metadata("https://doi.org/10.1371/journal.pone.0234245")
    assert meta["DOI"].lower() == "10.1371/journal.pone.0234245"


def test_crossref_metadata_raises_for_unknown_doi() -> None:
    with pytest.raises(LookupError):
        crossref_metadata("10.9999/this-doi-does-not-exist-zzzz")
