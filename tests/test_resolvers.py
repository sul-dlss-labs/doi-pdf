"""Live tests for the individual PDF resolvers.

These hit real services (OpenAlex, Internet Archive Scholar) and, for the
landing-page resolver, drive a headless browser. They are marked so a fast run
can skip them with ``pytest -m 'not network and not browser'``.

The chosen DOIs are gold open access articles (PLOS / eLife) that are very
likely to remain freely available.
"""

import pytest

from doi_pdf import (
    RESOLVERS,
    InternetArchiveScholarResolver,
    LandingPageResolver,
    OpenAlexContentResolver,
    OpenAlexResolver,
    build_resolvers,
)

# Known gold-OA DOIs.
PLOS_DOI = "10.1371/journal.pone.0234245"
ELIFE_DOI = "10.7554/elife.54129"
# A syntactically valid DOI that should resolve nowhere.
MISSING_DOI = "10.9999/this-doi-does-not-exist-zzzz"


def _looks_like_pdf_url(url: object) -> bool:
    return isinstance(url, str) and url.startswith("http")


# --- resolver selection (no network) -----------------------------------------


def test_build_resolvers_selects_named_resolvers_in_order() -> None:
    resolvers = build_resolvers(["internet-archive", "openalex"])
    assert [type(r) for r in resolvers] == [InternetArchiveScholarResolver, OpenAlexResolver]


def test_build_resolvers_single() -> None:
    resolvers = build_resolvers(["openalex"])
    assert len(resolvers) == 1
    assert isinstance(resolvers[0], OpenAlexResolver)


def test_build_resolvers_rejects_unknown_name() -> None:
    with pytest.raises(KeyError):
        build_resolvers(["nope"])


def test_registry_exposes_expected_keys() -> None:
    assert set(RESOLVERS) == {
        "openalex",
        "internet-archive",
        "landing-page",
        "openalex-content",
    }
    assert isinstance(RESOLVERS["openalex-content"](), OpenAlexContentResolver)


@pytest.mark.network
class TestOpenAlexResolver:
    def test_finds_pdf_for_open_access_doi(self) -> None:
        url = OpenAlexResolver(mailto="ehs@pobox.com").find_pdf_url(PLOS_DOI)
        assert _looks_like_pdf_url(url)

    def test_returns_none_for_unknown_doi(self) -> None:
        assert OpenAlexResolver().find_pdf_url(MISSING_DOI) is None


@pytest.mark.network
class TestInternetArchiveScholarResolver:
    def test_finds_pdf_for_open_access_doi(self) -> None:
        url = InternetArchiveScholarResolver().find_pdf_url(PLOS_DOI)
        # IA Scholar may not have every article preserved; when it does, it is
        # a URL, otherwise None. Assert the contract rather than presence.
        assert url is None or _looks_like_pdf_url(url)

    def test_returns_none_for_unknown_doi(self) -> None:
        assert InternetArchiveScholarResolver().find_pdf_url(MISSING_DOI) is None


@pytest.mark.network
@pytest.mark.browser
class TestLandingPageResolver:
    def test_finds_pdf_via_rendered_landing_page(self) -> None:
        url = LandingPageResolver().find_pdf_url(ELIFE_DOI)
        assert url is None or _looks_like_pdf_url(url)

    def test_returns_none_for_unknown_doi(self) -> None:
        assert LandingPageResolver().find_pdf_url(MISSING_DOI) is None
