"""Tests for the headless-browser PDF download fallback.

The challenge-detection and profile helpers are exercised offline with fakes;
the actual download paths are marked ``network``/``browser`` and need a real
``playwright install``.
"""

from pathlib import Path

import pytest

from doi_pdf import browser


class FakePage:
    """A stand-in for a Playwright Page exposing just title/query_selector."""

    def __init__(self, title: str = "", selector_hit: bool = False) -> None:
        self._title = title
        self._hit = selector_hit

    def title(self) -> str:
        return self._title

    def query_selector(self, _selector: str) -> object | None:
        return object() if self._hit else None


def test_profile_dir_honors_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "profile"
    monkeypatch.setenv("DOI_PDF_PROFILE_DIR", str(target))
    assert browser._profile_dir() == target
    assert target.is_dir()  # created on demand


def test_looks_like_challenge_detects_cloudflare_title() -> None:
    assert browser._looks_like_challenge(FakePage(title="Just a moment...")) is True


def test_looks_like_challenge_detects_challenge_markup() -> None:
    assert browser._looks_like_challenge(FakePage(selector_hit=True)) is True


def test_looks_like_challenge_passes_an_ordinary_page() -> None:
    assert browser._looks_like_challenge(FakePage(title="Some Article | Journal")) is False


# --- Live download paths (need network + `playwright install`) ----------------

# A gold-OA PLOS article whose PDF a browser can fetch directly.
PLOS_PDF = (
    "https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0234245&type=printable"
)


@pytest.mark.network
@pytest.mark.browser
def test_download_pdf_returns_pdf_bytes() -> None:
    data = browser.download_pdf(PLOS_PDF)
    assert data is not None
    assert data.startswith(b"%PDF")


@pytest.mark.network
@pytest.mark.browser
def test_download_pdf_returns_none_for_non_pdf() -> None:
    # A normal HTML page is not a PDF, so the fallback should decline it.
    assert browser.download_pdf("https://example.com/") is None


# An eScholarship item page is an HTML viewer that embeds the PDF rather than
# serving it directly; the browser fallback should still extract the file.
ESCHOLARSHIP_VIEWER = "https://escholarship.org/uc/item/4vk4m26c"


@pytest.mark.network
@pytest.mark.browser
def test_download_pdf_extracts_pdf_embedded_in_viewer_page() -> None:
    data = browser.download_pdf(ESCHOLARSHIP_VIEWER)
    assert data is not None
    assert data.startswith(b"%PDF")
