"""Live CrossRef and DataCite metadata tests (network)."""

import pytest

from doi_pdf import crossref_metadata, datacite_metadata

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


def test_crossref_metadata_percent_encodes_doi() -> None:
    # Wiley SICI DOIs contain <>;: and end in '#', which would truncate an
    # unencoded URL (CrossRef then 404s).
    doi = "10.1002/(sici)1097-0282(1996)40:1<1::aid-bip1>3.0.co;2-#"
    meta = crossref_metadata(doi)
    assert meta["DOI"].lower() == doi


def test_datacite_metadata_does_not_truncate_at_fragment() -> None:
    # Unencoded, '#foo' is dropped and DataCite returns 10.48550/arxiv.1706.03762.
    with pytest.raises(LookupError):
        datacite_metadata("10.48550/arxiv.1706.03762#foo")


def test_datacite_metadata_returns_record_for_arxiv_doi() -> None:
    # arXiv DOIs are registered with DataCite, not CrossRef.
    meta = datacite_metadata("10.48550/arXiv.1706.03762")
    assert meta["id"].lower() == "10.48550/arxiv.1706.03762"
    assert meta["attributes"]["titles"]


def test_datacite_metadata_raises_for_unknown_doi() -> None:
    with pytest.raises(LookupError):
        datacite_metadata("10.9999/this-doi-does-not-exist-zzzz")
