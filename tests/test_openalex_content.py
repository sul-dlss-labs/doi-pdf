"""Tests for the OpenAlex full-text PDF service code path.

The key-gated tests only run when ``OPENALEX_API_KEY`` is available (set it in a
local ``.env``; tests/conftest.py loads it). The paid service is a last resort,
so it lives in its own resolver placed last in the default order. See
https://developers.openalex.org/download/full-text-pdfs
"""

import os

import pytest

from doi_pdf import (
    LandingPageResolver,
    OpenAlexContentResolver,
    OpenAlexResolver,
    default_resolvers,
)

# OpenAlex reports has_content.pdf == True for this PLOS article.
CONTENT_DOI = "10.1371/journal.pone.0234245"

requires_key = pytest.mark.skipif(
    not os.environ.get("OPENALEX_API_KEY"),
    reason="set OPENALEX_API_KEY (e.g. in .env) to exercise the OpenAlex full-text service",
)


@pytest.mark.network
@requires_key
def test_content_resolver_returns_content_url_with_key() -> None:
    url = OpenAlexContentResolver(api_key=os.environ["OPENALEX_API_KEY"]).find_pdf_url(CONTENT_DOI)
    assert url is not None
    assert url.startswith("https://content.openalex.org/works/")
    # The key is appended as a query param (asserted without echoing its value).
    assert "api_key=" in url
    assert url.split("api_key=", 1)[1] != ""


def test_content_resolver_without_key_returns_none() -> None:
    # No key -> short-circuits before any request, so no network is needed.
    assert OpenAlexContentResolver(api_key=None).find_pdf_url(CONTENT_DOI) is None


@pytest.mark.network
def test_plain_openalex_resolver_never_uses_content_service() -> None:
    url = OpenAlexResolver().find_pdf_url(CONTENT_DOI)
    assert url is not None
    assert "content.openalex.org" not in url


@requires_key
def test_default_resolvers_put_content_service_last() -> None:
    resolvers = default_resolvers()
    # Free OpenAlex first, paid full-text service strictly last.
    assert isinstance(resolvers[0], OpenAlexResolver)
    assert isinstance(resolvers[-1], OpenAlexContentResolver)
    # The browser landing-page resolver comes before the paid service.
    assert any(isinstance(r, LandingPageResolver) for r in resolvers[:-1])


def test_default_resolvers_omit_content_service_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    resolvers = default_resolvers()
    assert not any(isinstance(r, OpenAlexContentResolver) for r in resolvers)
