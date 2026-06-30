"""Headless-browser fallback for fetching PDFs that block plain HTTP clients.

Some publishers refuse a plain ``requests`` download (missing referer/cookies,
JavaScript-gated links, light bot checks) but will serve the PDF to a real
browser. Others resolve a "PDF" URL to an HTML *viewer* page that only embeds
the PDF (e.g. eScholarship and many institutional repositories). This module
drives headless Chromium to handle both: it retries the download and, when it
lands on an HTML page, digs out the embedded PDF.

It is genuinely best-effort: publishers behind an aggressive bot challenge
(e.g. Cloudflare "managed challenge") detect and block headless Chromium too,
in which case ``download_pdf`` simply returns ``None`` and logs why.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._http import BROWSER_USER_AGENT, redact

if TYPE_CHECKING:
    from playwright.sync_api import APIRequestContext, Page

log = logging.getLogger(__name__)

# How long to let an embedded viewer start loading its PDF before we look.
_EMBED_SETTLE_MS = 3000
# Cap how many embedded candidates we try, to bound latency.
_MAX_CANDIDATES = 6


def download_pdf(url: str, timeout: float = 30.0) -> bytes | None:
    """Fetch *url* with a headless browser, returning PDF bytes or ``None``.

    Navigates to the URL (establishing cookies / passing light JS challenges).
    If the response is itself a PDF it is returned directly; if it is an HTML
    page, the embedded PDF is extracted (see :func:`_embedded_pdf`). Returns the
    body only when it is a real PDF (``%PDF`` magic).
    """
    # Imported lazily so importing doi_pdf does not require a browser install.
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright

    log.info("[browser] fetching %s", redact(url))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=BROWSER_USER_AGENT, accept_downloads=True)
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

            # If the navigation itself delivered the PDF, use it.
            if response is not None:
                try:
                    navigated = response.body()
                except PlaywrightError:
                    navigated = b""
                if navigated.startswith(b"%PDF"):
                    log.info("[browser] downloaded %d bytes via navigation", len(navigated))
                    return navigated

            # The page is HTML (a viewer, a challenge, or a repository record);
            # give an embedded viewer a moment, then hunt for the PDF.
            page.wait_for_timeout(_EMBED_SETTLE_MS)
            return _embedded_pdf(page, context.request, url, pdf_resources, timeout)
        finally:
            browser.close()


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
    browser context (so cookies carry over).
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
