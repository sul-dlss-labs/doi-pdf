"""Pluggable PDF resolvers.

A resolver knows how to turn a bare DOI into a direct URL for an open access
PDF, or ``None`` if it cannot find one. Resolvers are tried in order by
:func:`doi_pdf.core.find_pdf_url`, so the default list is ordered cheapest /
most-reliable first.

Resolvers emit diagnostics on the ``doi_pdf`` logger at ``INFO`` level (which
the CLI's ``--verbose`` flag turns on) describing the service queried, the URL,
and the result.
"""

from __future__ import annotations

import html
import logging
import os
import re
from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable
from urllib.parse import urljoin

import requests

from ._http import DEFAULT_TIMEOUT, USER_AGENT, redact

log = logging.getLogger(__name__)


@runtime_checkable
class Resolver(Protocol):
    """Anything that can attempt to find a PDF URL for a DOI."""

    #: Human-readable service name, used in diagnostics.
    name: str

    def find_pdf_url(self, doi: str) -> str | None:
        """Return a direct PDF URL for *doi*, or ``None`` if not found."""
        ...


class OpenAlexResolver:
    """Look up the DOI in OpenAlex and return its open access PDF URL.

    Uses the OpenAlex works API and the ``best_oa_location`` / ``locations`` /
    ``open_access`` fields. This is free; the paid full-text service lives in
    :class:`OpenAlexContentResolver`. See
    https://developers.openalex.org/download/full-text-pdfs
    """

    name = "OpenAlex"
    API = "https://api.openalex.org/works/"

    def __init__(self, mailto: str | None = None) -> None:
        self.mailto = mailto

    def find_pdf_url(self, doi: str) -> str | None:
        url = self.API + "https://doi.org/" + doi
        params = {"mailto": self.mailto} if self.mailto else {}
        log.info("[%s] GET %s", self.name, url)
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code == 404:
            log.info("[%s] not indexed (404)", self.name)
            return None
        resp.raise_for_status()
        work = resp.json()

        # Prefer locations that expose an explicit PDF link, best one first.
        best = work.get("best_oa_location") or {}
        candidates: list[str | None] = [best.get("pdf_url")]
        candidates += [loc.get("pdf_url") for loc in work.get("locations") or []]
        # oa_url is sometimes a landing page, so it is only a last resort.
        candidates.append((work.get("open_access") or {}).get("oa_url"))

        for candidate in candidates:
            if candidate:
                log.info("[%s] found PDF: %s", self.name, candidate)
                return candidate
        log.info("[%s] no open access PDF in record", self.name)
        return None


class OpenAlexContentResolver:
    """Fetch the PDF from OpenAlex's paid full-text service as a last resort.

    Requires an ``api_key``. When OpenAlex holds the full text for a work
    (``has_content.pdf``), this returns its ``content.openalex.org`` link with
    the key attached. Each download costs ~$0.01, so it is placed last in the
    default resolver order. See
    https://developers.openalex.org/download/full-text-pdfs
    """

    name = "OpenAlex full-text service"
    API = "https://api.openalex.org/works/"

    def __init__(self, api_key: str | None = None, mailto: str | None = None) -> None:
        self.api_key = api_key
        self.mailto = mailto

    def find_pdf_url(self, doi: str) -> str | None:
        if not self.api_key:
            return None
        url = self.API + "https://doi.org/" + doi
        params = {"api_key": self.api_key}
        if self.mailto:
            params["mailto"] = self.mailto
        log.info("[%s] GET %s", self.name, url)
        resp = requests.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code == 404:
            log.info("[%s] not indexed (404)", self.name)
            return None
        resp.raise_for_status()
        work = resp.json()

        if not (work.get("has_content") or {}).get("pdf"):
            log.info("[%s] no full text available", self.name)
            return None
        content_pdf = (work.get("content_urls") or {}).get("pdf")
        if not content_pdf:
            log.info("[%s] no content_urls.pdf in record", self.name)
            return None
        sep = "&" if "?" in content_pdf else "?"
        content_url = f"{content_pdf}{sep}api_key={self.api_key}"
        log.info("[%s] using full-text service: %s", self.name, redact(content_url))
        return content_url


class InternetArchiveScholarResolver:
    """Look up the DOI in Internet Archive Scholar (https://scholar.archive.org/)
    and return a preserved fulltext PDF URL if one exists.

    IA Scholar serves each preserved paper through a stable
    ``/work/<ident>/access/wayback/<original-url>`` link, which we scrape from
    the search results for the DOI.
    """

    name = "Internet Archive Scholar"
    SEARCH = "https://scholar.archive.org/search"
    BASE = "https://scholar.archive.org"
    # The "access" link to a preserved fulltext copy on a result.
    _ACCESS_RE = re.compile(r'href="(/work/[^"]+/access/[^"]+)"')

    def find_pdf_url(self, doi: str) -> str | None:
        query = f'doi:"{doi}"'
        log.info("[%s] GET %s?q=%s", self.name, self.SEARCH, query)
        resp = requests.get(
            self.SEARCH,
            params={"q": query},
            headers={"User-Agent": USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()

        paths: list[str] = [html.unescape(m) for m in self._ACCESS_RE.findall(resp.text)]
        if not paths:
            log.info("[%s] no preserved fulltext", self.name)
            return None
        # Prefer a link that clearly points at a PDF, otherwise the first hit.
        path = next((p for p in paths if ".pdf" in p.lower()), paths[0])
        result = urljoin(self.BASE, path)
        log.info("[%s] found PDF: %s", self.name, result)
        return result


class LandingPageResolver:
    """Resolve the DOI to its publisher landing page, render it with a headless
    browser, and scrape a link to the PDF.

    Rendering is required because many landing pages inject the PDF link with
    JavaScript or expose it through a ``<meta name="citation_pdf_url">`` tag
    (the Google Scholar convention) that we read after the page loads.
    """

    name = "DOI landing page"

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def find_pdf_url(self, doi: str) -> str | None:
        # Imported lazily so the rest of the library works without a browser.
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright

        url = "https://doi.org/" + doi
        log.info("[%s] rendering %s", self.name, url)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                try:
                    response = page.goto(
                        url,
                        timeout=self.timeout * 1000,
                        wait_until="domcontentloaded",
                    )
                except PlaywrightTimeout:
                    log.info("[%s] timed out loading page", self.name)
                    return None
                if response is not None and response.status >= 400:
                    log.info("[%s] landing page returned HTTP %s", self.name, response.status)
                    return None
                log.info("[%s] resolved to %s", self.name, page.url)

                # The Google Scholar citation tag is the most reliable signal.
                meta = page.query_selector('meta[name="citation_pdf_url"]')
                if meta:
                    content = meta.get_attribute("content")
                    if content:
                        log.info("[%s] found citation_pdf_url: %s", self.name, content)
                        return content

                # Otherwise fall back to the first anchor that points at a PDF.
                anchor_pdf: str | None = page.eval_on_selector_all(
                    "a[href]",
                    """els => {
                        for (const el of els) {
                            const h = el.href || "";
                            if (h.toLowerCase().includes(".pdf")) return h;
                        }
                        return null;
                    }""",
                )
                if anchor_pdf:
                    log.info("[%s] found PDF link: %s", self.name, anchor_pdf)
                else:
                    log.info("[%s] no PDF link on page", self.name)
                return anchor_pdf
            finally:
                browser.close()


# Selectable resolvers keyed by short name, in default priority order. Each
# factory reads its configuration (mailto, API key) from the environment at
# call time, so load any .env before building.
RESOLVERS: dict[str, Callable[[], Resolver]] = {
    "openalex": lambda: OpenAlexResolver(mailto=os.environ.get("OPENALEX_MAILTO")),
    "internet-archive": lambda: InternetArchiveScholarResolver(),
    "landing-page": lambda: LandingPageResolver(),
    "openalex-content": lambda: OpenAlexContentResolver(
        api_key=os.environ.get("OPENALEX_API_KEY"),
        mailto=os.environ.get("OPENALEX_MAILTO"),
    ),
}


def build_resolvers(names: Sequence[str]) -> list[Resolver]:
    """Build resolver instances for the given short *names*, in order.

    Raises ``KeyError`` (via the registry) for an unknown name.
    """
    return [RESOLVERS[name]() for name in names]


def default_resolvers() -> list[Resolver]:
    """Return a fresh default resolver list in priority order.

    Free sources are tried first. When ``OPENALEX_API_KEY`` is set, the paid
    OpenAlex full-text service is appended as a last resort. ``OPENALEX_MAILTO``
    is used for the polite pool when present.
    """
    names = ["openalex", "internet-archive", "landing-page"]
    if os.environ.get("OPENALEX_API_KEY"):
        names.append("openalex-content")
    return build_resolvers(names)
