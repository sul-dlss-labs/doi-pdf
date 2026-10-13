"""Tests for the headless-browser PDF download fallback.

The challenge-detection and profile helpers are exercised offline with fakes;
the actual download paths are marked ``network``/``browser`` and need a real
``playwright install``.
"""

from pathlib import Path

import pytest

from doi_pdf import browser


class FakePage:
    """A stand-in for a Playwright Page exposing just what detection uses.

    ``aws_waf`` simulates an AWS WAF interstitial (``window.gokuProps`` set);
    ``aws_captcha`` adds its CAPTCHA script. ``escalate_after`` turns the page
    into the CAPTCHA after that many waits, as AWS WAF does when its JavaScript
    challenge fails.
    """

    def __init__(
        self,
        title: str = "",
        selector_hit: bool = False,
        aws_waf: bool = False,
        aws_captcha: bool = False,
        escalate_after: int | None = None,
    ) -> None:
        self._title = title
        self._hit = selector_hit
        self._aws_waf = aws_waf
        self._aws_captcha = aws_captcha
        self._escalate_after = escalate_after
        self.waits = 0

    def title(self) -> str:
        return self._title

    def query_selector(self, selector: str) -> object | None:
        if selector == browser._AWS_WAF_CAPTCHA_SELECTOR:
            return object() if self._aws_captcha else None
        return object() if self._hit else None

    def evaluate(self, expression: str) -> object:
        assert expression == browser._AWS_WAF_INTERSTITIAL_JS
        return self._aws_waf

    def wait_for_timeout(self, timeout: float) -> None:
        self.waits += 1
        if self._escalate_after is not None and self.waits >= self._escalate_after:
            self._aws_captcha = True


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


def test_aws_waf_challenge_is_a_challenge_but_not_a_captcha() -> None:
    # The 202 "x-amzn-waf-action: challenge" page: blank title, gokuProps set.
    page = FakePage(aws_waf=True)
    assert browser._looks_like_challenge(page) is True
    assert browser._looks_like_captcha(page) is False


def test_aws_waf_captcha_is_detected() -> None:
    # The 405 "x-amzn-waf-action: captcha" page ("Human Verification").
    page = FakePage(title="Human Verification", aws_waf=True, aws_captcha=True)
    assert browser._looks_like_captcha(page) is True


def test_aws_captcha_script_alone_is_not_an_interstitial() -> None:
    # A normal page may embed AWS's CAPTCHA API in a form; that is not a wall.
    page = FakePage(title="Some Article | Journal", aws_captcha=True)
    assert browser._looks_like_challenge(page) is False
    assert browser._looks_like_captcha(page) is False


def test_wait_out_challenge_stops_when_it_escalates_to_a_captcha() -> None:
    page = FakePage(aws_waf=True, escalate_after=2)
    assert browser._wait_out_challenge(page, "https://x.example/") is False
    # Gave up as soon as the CAPTCHA appeared, not after the full budget.
    assert page.waits == 2


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


# An OJS "galley view" page is an HTML viewer that embeds the PDF rather than
# serving it directly: a plain GET returns only HTML, and the pdf.js iframe that
# loads the PDF is inserted by JavaScript. The browser fallback should still
# extract the file. (EBLIP, a gold-OA journal hosted by the University of
# Alberta Library. eScholarship used to serve here but is now behind an AWS WAF
# CAPTCHA.)
OJS_GALLEY_VIEWER = (
    "https://journals.library.ualberta.ca/eblip/index.php/EBLIP/article/view/31094/23133"
)


@pytest.mark.network
@pytest.mark.browser
def test_download_pdf_extracts_pdf_embedded_in_viewer_page() -> None:
    data = browser.download_pdf(OJS_GALLEY_VIEWER)
    assert data is not None
    assert data.startswith(b"%PDF")
