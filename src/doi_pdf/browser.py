"""Headless-browser fallback for fetching PDFs that block plain HTTP clients.

Some publishers refuse a plain ``requests`` download (missing referer/cookies,
JavaScript-gated links, light bot checks) but will serve the PDF to a real
browser. Others resolve a "PDF" URL to an HTML *viewer* page that only embeds
the PDF (e.g. OJS journal article pages and many institutional repositories).
This module drives Chromium to handle both: it retries the download and, when
it lands on an HTML page, digs out the embedded PDF.

To get past CDN bot walls (Cloudflare, AWS WAF) without logging in, it leans on
three things rather than on solving any challenge:

* **A persistent profile.** Cookies -- notably Cloudflare's ``cf_clearance`` --
  are kept in a user-data dir between runs, so a challenge passed once is not
  re-fought on the next download.
* **A less automated-looking browser.** The UA matches the host OS (see
  :mod:`doi_pdf._http`), ``navigator.webdriver`` is unset, and the browser can
  be run headful under a virtual display (set ``DOI_PDF_HEADLESS=0``), which
  passes managed challenges far more reliably than headless.
* **Patience.** Cloudflare's non-interactive challenges clear themselves within
  seconds for a browser that passes their fingerprint checks, so we wait the
  interstitial out instead of giving up immediately.

The browser itself is optional at runtime: if Playwright's Chromium has not
been installed (``playwright install chromium``), :func:`browser_available`
says so and callers skip the browser instead of failing.

It is still best-effort: a site demanding an *interactive* CAPTCHA (one a human
is meant to click/solve) is left alone -- ``download_pdf`` returns ``None`` and
logs why. We do not attempt to defeat those. (AWS WAF, for one, escalates a
failed JavaScript challenge to such a CAPTCHA; we stop waiting as soon as it
does.)

Environment variables:

* ``DOI_PDF_HEADLESS`` -- ``0`` runs the browser headful (needs a display, e.g.
  Xvfb on a server); anything else, or unset, runs headless (the default).
* ``DOI_PDF_PROFILE_DIR`` -- where to keep the persistent browser profile;
  defaults to ``~/.cache/doi-pdf/chromium-profile``.
"""

from __future__ import annotations

import functools
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ._http import BROWSER_CLIENT_HINTS, BROWSER_USER_AGENT, redact

if TYPE_CHECKING:
    from playwright.sync_api import APIRequestContext, BrowserContext, Page, Playwright


class _ChallengeProbe(Protocol):
    """The slice of a Playwright ``Page`` that challenge detection relies on."""

    def title(self) -> str: ...

    def query_selector(self, selector: str, /) -> object | None: ...

    def evaluate(self, expression: str, /) -> object: ...


class _ChallengeWaiter(_ChallengeProbe, Protocol):
    """A :class:`_ChallengeProbe` that can also pause, for waiting a challenge out."""

    def wait_for_timeout(self, timeout: float, /) -> None: ...


log = logging.getLogger(__name__)

# How long to let an embedded viewer start loading its PDF before we look.
_EMBED_SETTLE_MS = 3000
# Cap how many embedded candidates we try, to bound latency.
_MAX_CANDIDATES = 6
# Longest we wait for a Cloudflare-style interstitial to clear on its own.
_CHALLENGE_TIMEOUT_S = 20.0

# Removes the clearest "this is automation" signal a page can read in JS. This
# normalizes the browser's fingerprint; it does not solve any challenge.
_STEALTH_INIT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"

# Page titles Cloudflare serves while a challenge is running.
_CHALLENGE_TITLES = {"just a moment...", "attention required! | cloudflare"}
# Markers of an *in-flight* challenge in the page's DOM. Deliberately narrow:
# the ``/cdn-cgi/challenge-platform/`` script Cloudflare injects is also present
# on ordinary protected pages, so matching on it mis-flags benign pages as
# challenges -- we only look for the interstitial's own widgets.
_CHALLENGE_SELECTOR = (
    "#challenge-form, #challenge-running, iframe[src*='challenges.cloudflare.com']"
)

# AWS WAF's challenge and CAPTCHA interstitials both configure themselves via an
# inline ``window.gokuProps``. We key on that rather than on any ``awswaf.com``
# script, because ordinary pages may load AWS's ``challenge.js`` SDK too.
_AWS_WAF_INTERSTITIAL_JS = "() => typeof window.gokuProps !== 'undefined'"
# On an AWS WAF interstitial, this script means it is the interactive CAPTCHA
# (a "Human Verification" puzzle), which never clears without a person.
_AWS_WAF_CAPTCHA_SELECTOR = "script[src*='.captcha.awswaf.com/']"


def _profile_dir() -> Path:
    """Return (creating if needed) the persistent browser-profile directory."""
    override = os.environ.get("DOI_PDF_PROFILE_DIR")
    path = Path(override) if override else Path.home() / ".cache" / "doi-pdf" / "chromium-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _headless() -> bool:
    """Return whether the browser fallback runs headless (``DOI_PDF_HEADLESS``)."""
    return os.environ.get("DOI_PDF_HEADLESS", "1") != "0"


# What Playwright says when the browser for a launch has not been downloaded.
_MISSING_BROWSER_MESSAGE = "Executable doesn't exist"

# Shown wherever the missing browser is reported.
INSTALL_HINT = "playwright install chromium"


def browser_available(headless: bool | None = None) -> bool:
    """Return whether Playwright's Chromium can be launched in this mode.

    *headless* defaults to the configured mode (``DOI_PDF_HEADLESS``). The
    modes need different binaries -- headless launches a separate
    ``chromium-headless-shell`` -- so each is checked by actually launching
    it once; the answer is cached for the process.
    """
    return _probe_launch(_headless() if headless is None else headless)


@functools.cache
def _probe_launch(headless: bool) -> bool:
    """Launch and close Chromium once; ``False`` only if it is not installed.

    Any other launch failure (e.g. a headful run with no display) counts as
    available, so the real launch raises it as before: the probe only adds a
    way to skip the browser, never a new way to fail.
    """
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            p.chromium.launch(headless=headless).close()
    except PlaywrightError as exc:
        if _MISSING_BROWSER_MESSAGE in str(exc):
            mode = "headless" if headless else "headful"
            log.info("[browser] Chromium (%s) is not installed; run: %s", mode, INSTALL_HINT)
            return False
    return True


def _launch_context(p: Playwright) -> BrowserContext:
    """Launch a persistent Chromium context configured to look ordinary."""
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(_profile_dir()),
        headless=_headless(),
        user_agent=BROWSER_USER_AGENT,
        extra_http_headers=BROWSER_CLIENT_HINTS,
        accept_downloads=True,
        locale="en-US",
        viewport={"width": 1280, "height": 800},
    )
    context.add_init_script(_STEALTH_INIT)
    return context


def _is_aws_waf_interstitial(page: _ChallengeProbe) -> bool:
    """Return whether *page* is an AWS WAF challenge or CAPTCHA interstitial."""
    from playwright.sync_api import Error as PlaywrightError

    try:
        return page.evaluate(_AWS_WAF_INTERSTITIAL_JS) is True
    except PlaywrightError:
        return False


def _looks_like_challenge(page: _ChallengeProbe) -> bool:
    """Return whether *page* is currently showing a CDN bot-check interstitial."""
    from playwright.sync_api import Error as PlaywrightError

    try:
        title = (page.title() or "").strip().lower()
        if title in _CHALLENGE_TITLES:
            return True
        if page.query_selector(_CHALLENGE_SELECTOR) is not None:
            return True
    except PlaywrightError:
        return False
    return _is_aws_waf_interstitial(page)


def _looks_like_captcha(page: _ChallengeProbe) -> bool:
    """Return whether *page* is an interactive CAPTCHA, which we never attempt."""
    from playwright.sync_api import Error as PlaywrightError

    if not _is_aws_waf_interstitial(page):
        return False
    try:
        return page.query_selector(_AWS_WAF_CAPTCHA_SELECTOR) is not None
    except PlaywrightError:
        return False


def _wait_out_challenge(page: _ChallengeWaiter, url: str) -> bool:
    """Wait for a non-interactive challenge on *page* to clear itself.

    Returns whether the interstitial went away within :data:`_CHALLENGE_TIMEOUT_S`.
    We only *wait*; an interactive CAPTCHA that needs a human is never solved
    here. If the challenge escalates to one, we stop waiting at once.
    """
    log.info("[browser] bot-check interstitial at %s; waiting for it to clear", redact(url))
    waited_ms = 0.0
    budget_ms = _CHALLENGE_TIMEOUT_S * 1000
    while waited_ms < budget_ms:
        page.wait_for_timeout(1000)
        waited_ms += 1000
        if _looks_like_captcha(page):
            log.info(
                "[browser] interstitial escalated to an interactive CAPTCHA; not attempting it"
            )
            return False
        if not _looks_like_challenge(page):
            log.info("[browser] interstitial cleared after %.0fs", waited_ms / 1000)
            return True
    log.info("[browser] interstitial did not clear within %.0fs", _CHALLENGE_TIMEOUT_S)
    return False


def download_pdf(url: str, timeout: float = 30.0) -> bytes | None:
    """Fetch *url* with a browser, returning PDF bytes or ``None``.

    Navigates to the URL using a persistent profile (so cookies such as
    Cloudflare's ``cf_clearance`` carry over between runs), waiting out a
    non-interactive bot-check interstitial if one appears. If the response is
    itself a PDF it is returned directly; if it is an HTML page, the embedded
    PDF is extracted (see :func:`_embedded_pdf`). Returns the body only when it
    is a real PDF (``%PDF`` magic), and ``None`` without trying when Chromium
    is not installed (see :func:`browser_available`).
    """
    if not browser_available():
        log.info("[browser] skipping %s: Chromium is not installed", redact(url))
        return None

    # Imported lazily so importing doi_pdf does not require a browser install.
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    log.info("[browser] fetching %s", redact(url))
    with sync_playwright() as p:
        context = _launch_context(p)
        try:
            page = context.new_page()

            # Record any PDF the page loads on its own (viewers, iframes, embeds).
            pdf_resources: list[str] = []

            def _note_pdf(response: object) -> None:
                resp_url = getattr(response, "url", "")
                headers = getattr(response, "headers", {}) or {}
                if "application/pdf" in headers.get("content-type", "").lower():
                    pdf_resources.append(resp_url)

            page.on("response", _note_pdf)

            response = None
            try:
                response = page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            except PlaywrightTimeout:
                log.info("[browser] timed out loading %s", redact(url))
                return None
            except PlaywrightError as exc:
                # Navigation aborts when the response is served as a download;
                # we fall back to extracting / re-requesting below.
                log.info("[browser] navigation interrupted (%s)", type(exc).__name__)

            # A CDN bot wall may stand between us and the content. Give a
            # self-clearing challenge a chance before treating the page as real.
            # Whether or not it clears, we still fall through to PDF extraction
            # below -- waiting is a bonus, never a new way to fail.
            if _looks_like_captcha(page):
                log.info("[browser] interactive CAPTCHA at %s; not attempting it", redact(url))
            elif _looks_like_challenge(page):
                _wait_out_challenge(page, url)

            # If the navigation itself delivered the PDF, use it. (After a
            # challenge this response is the stale interstitial -- not a PDF --
            # so it harmlessly falls through to re-extraction below.)
            if response is not None:
                try:
                    navigated = response.body()
                except PlaywrightError:
                    navigated = b""
                if navigated.startswith(b"%PDF"):
                    log.info("[browser] downloaded %d bytes via navigation", len(navigated))
                    return navigated

            # The page is HTML (a viewer, a record page, or post-challenge
            # content); give an embedded viewer a moment, then hunt for the PDF.
            page.wait_for_timeout(_EMBED_SETTLE_MS)
            return _embedded_pdf(page, context.request, url, pdf_resources, timeout)
        finally:
            context.close()


def _embedded_pdf(
    page: Page,
    request: APIRequestContext,
    url: str,
    pdf_resources: list[str],
    timeout: float,
) -> bytes | None:
    """Find a PDF embedded in the rendered *page* and return its bytes.

    Candidates, in order of reliability: PDFs the page itself loaded, the
    ``citation_pdf_url`` meta tag, any ``embed``/``iframe``/``object``/anchor
    pointing at a ``.pdf``, and finally the original URL re-requested within the
    browser context (so cookies, including any clearance cookie, carry over).
    """
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    candidates: list[str] = list(pdf_resources)

    meta = page.query_selector('meta[name="citation_pdf_url"]')
    if meta:
        content = meta.get_attribute("content")
        if content:
            candidates.append(content)

    embedded: list[str] = page.eval_on_selector_all(
        "embed, iframe, object, a",
        """els => els.map(e => e.src || e.data || e.href || "")
                    .filter(u => u && u.toLowerCase().includes('.pdf'))""",
    )
    candidates += embedded
    candidates.append(url)

    # De-duplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            ordered.append(candidate)

    for candidate in ordered[:_MAX_CANDIDATES]:
        try:
            resp = request.get(candidate, timeout=timeout * 1000)
        except (PlaywrightError, PlaywrightTimeout) as exc:
            log.info("[browser] request for %s failed (%s)", redact(candidate), type(exc).__name__)
            continue
        if not resp.ok:
            log.info("[browser] HTTP %s for %s", resp.status, redact(candidate))
            continue
        body = resp.body()
        if body.startswith(b"%PDF"):
            note = " (embedded)" if candidate != url else ""
            log.info("[browser] downloaded %d bytes from %s%s", len(body), redact(candidate), note)
            return body

    log.info("[browser] no PDF found at or embedded in %s", redact(url))
    return None
