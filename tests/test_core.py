"""Tests for the pluggable resolver coordination in doi_pdf.core.

The coordinator logic is exercised with in-memory fake resolvers so these
tests are deterministic and need no network.
"""

import logging
from pathlib import Path

import pytest

from doi_pdf import core, find_pdf_url
from doi_pdf.core import fetch


class RecordingResolver:
    """A fake Resolver that records the DOIs it was asked about."""

    name = "recording"

    def __init__(self, result: str | None) -> None:
        self.result = result
        self.seen: list[str] = []

    def find_pdf_url(self, doi: str) -> str | None:
        self.seen.append(doi)
        return self.result


def test_find_pdf_url_returns_first_hit_and_short_circuits() -> None:
    first = RecordingResolver("https://example.org/a.pdf")
    second = RecordingResolver("https://example.org/b.pdf")

    url = find_pdf_url("10.1177/13548565231164759", resolvers=[first, second])

    assert url == "https://example.org/a.pdf"
    # Second resolver must not be consulted once the first one succeeds.
    assert second.seen == []


def test_find_pdf_url_falls_through_to_later_resolvers() -> None:
    miss = RecordingResolver(None)
    hit = RecordingResolver("https://example.org/found.pdf")

    url = find_pdf_url("10.1177/13548565231164759", resolvers=[miss, hit])

    assert url == "https://example.org/found.pdf"
    assert miss.seen and hit.seen


def test_find_pdf_url_returns_none_when_all_miss() -> None:
    a, b = RecordingResolver(None), RecordingResolver(None)
    assert find_pdf_url("10.1177/13548565231164759", resolvers=[a, b]) is None


def test_find_pdf_url_normalizes_before_dispatch() -> None:
    # Resolvers should receive the bare, normalized DOI, not the URL form.
    r = RecordingResolver(None)
    find_pdf_url("https://doi.org/10.1177/13548565231164759", resolvers=[r])
    assert r.seen == ["10.1177/13548565231164759"]


def test_find_pdf_url_logs_diagnostics(caplog: pytest.LogCaptureFixture) -> None:
    """Verbose diagnostics name the resolver tried and the chosen URL."""
    hit = RecordingResolver("https://example.org/found.pdf")
    with caplog.at_level(logging.INFO, logger="doi_pdf"):
        find_pdf_url("10.1177/13548565231164759", resolvers=[hit])
    blob = "\n".join(caplog.messages)
    assert "recording" in blob
    assert "https://example.org/found.pdf" in blob


class StubResolver:
    """A resolver returning a fixed URL, for download-fall-through tests."""

    def __init__(self, name: str, url: str | None) -> None:
        self.name = name
        self._url = url

    def find_pdf_url(self, doi: str) -> str | None:
        return self._url


def test_fetch_falls_through_to_next_resolver_when_download_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a resolver's URL won't download, fetch tries the next resolver."""
    monkeypatch.setattr(core, "crossref_metadata", lambda doi: {"DOI": doi})

    attempted: list[str] = []

    def fake_download(url: str, path: Path) -> Path | None:
        attempted.append(url)
        if url == "https://good.example/ok.pdf":
            path.write_bytes(b"%PDF-1.7 stub")
            return path
        return None  # simulate a blocked / non-PDF response

    monkeypatch.setattr(core, "_download_pdf", fake_download)

    blocked = StubResolver("blocked", "https://bad.example/no.pdf")
    working = StubResolver("works", "https://good.example/ok.pdf")
    result = core.fetch("10.1234/abc", dest=tmp_path, resolvers=[blocked, working])

    assert result.json_path is not None and result.json_path.exists()
    assert result.pdf_path is not None
    assert result.pdf_path.read_bytes().startswith(b"%PDF")
    assert result.resolver == "works"  # the report needs the winning resolver's name
    # Both resolvers' URLs were attempted, in order, before one succeeded.
    assert attempted == ["https://bad.example/no.pdf", "https://good.example/ok.pdf"]


def test_fetch_returns_no_pdf_when_every_download_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(core, "crossref_metadata", lambda doi: {"DOI": doi})
    monkeypatch.setattr(core, "_download_pdf", lambda url, path: None)

    a = StubResolver("a", "https://x.example/a.pdf")
    b = StubResolver("b", "https://x.example/b.pdf")
    result = core.fetch("10.1234/abc", dest=tmp_path, resolvers=[a, b])

    assert result.json_path is not None and result.json_path.exists()
    assert result.pdf_path is None
    assert result.resolver is None


@pytest.mark.network
@pytest.mark.browser
def test_fetch_writes_pdf_and_json(tmp_path: Path) -> None:
    """A successful fetch writes <stem>.pdf and <stem>.json into dest."""
    result = fetch("10.1371/journal.pone.0234245", dest=tmp_path)

    assert result.json_path == tmp_path / "10.1371-journal.pone.0234245.json"
    assert result.json_path is not None and result.json_path.exists()
    if result.pdf_path is not None:
        assert result.pdf_path == tmp_path / "10.1371-journal.pone.0234245.pdf"
        assert result.pdf_path.exists()
        assert result.pdf_path.read_bytes().startswith(b"%PDF")
        assert result.resolver  # a resolver name was recorded
