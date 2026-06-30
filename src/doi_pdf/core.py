"""High level coordination: find a PDF and download it alongside metadata."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import requests

from . import browser
from ._http import USER_AGENT, redact
from .doi import doi_filename, normalize_doi
from .metadata import crossref_metadata
from .resolvers import Resolver, default_resolvers

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FetchResult:
    """The outcome of :func:`fetch` for one DOI.

    - ``doi`` — the normalized DOI.
    - ``crossref`` — whether CrossRef metadata was found (and ``json_path`` written).
    - ``json_path`` — where the metadata was written, or ``None`` if unavailable.
    - ``pdf_path`` — where the PDF was written, or ``None`` if none was found.
    - ``resolver`` — the name of the resolver that produced the PDF, or ``None``.
    """

    doi: str
    crossref: bool
    json_path: Path | None
    pdf_path: Path | None
    resolver: str | None


def find_pdf_url(
    doi: str,
    resolvers: Sequence[Resolver] | None = None,
) -> str | None:
    """Return a PDF URL for *doi* using *resolvers* in order.

    The DOI is normalized first. Each resolver is tried in turn and the first
    non-``None`` result wins. Returns ``None`` if no resolver finds a PDF.
    If *resolvers* is ``None`` the default resolver list is used.
    """
    doi = normalize_doi(doi)
    if resolvers is None:
        resolvers = default_resolvers()
    log.info("looking for a PDF for %s", doi)
    for resolver in resolvers:
        name = getattr(resolver, "name", type(resolver).__name__)
        log.info("trying resolver: %s", name)
        url = resolver.find_pdf_url(doi)
        if url:
            log.info("using PDF from %s: %s", name, redact(url))
            return url
    log.info("no resolver found a PDF for %s", doi)
    return None


def _http_get(url: str) -> tuple[int, bytes, bool]:
    """GET *url*, returning ``(status_code, body, ok)``.

    When ``curl_cffi`` is installed the request impersonates Chrome's TLS/HTTP2
    fingerprint (and sends a matching Chrome UA), which clears the lighter
    Cloudflare / AWS WAF checks that reject Python's default TLS handshake
    regardless of headers -- often without needing the browser fallback at all.
    Falls back to plain ``requests`` (with the descriptive UA) when ``curl_cffi``
    is not available.
    """
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=60,
            allow_redirects=True,
        )
        return resp.status_code, resp.content, resp.ok

    resp = curl_requests.get(url, impersonate="chrome", timeout=60, allow_redirects=True)
    return resp.status_code, resp.content, resp.ok


def _http_pdf_bytes(url: str) -> bytes | None:
    """Download *url* with a plain HTTP client, returning bytes only if a PDF."""
    log.info("downloading PDF: %s", redact(url))
    status, content, ok = _http_get(url)
    if not ok:
        log.info("direct download failed: HTTP %s", status)
        return None
    if not content.startswith(b"%PDF"):
        log.info("direct download was not a PDF (got %d bytes)", len(content))
        return None
    return content


def _download_pdf(url: str, path: Path) -> Path | None:
    """Download *url* to *path*, returning the path only if a real PDF was saved.

    Tries a plain HTTP client first and, if that is blocked, retries once with a
    headless browser (see :mod:`doi_pdf.browser`).
    """
    data = _http_pdf_bytes(url)
    if data is None:
        log.info("retrying download with a headless browser")
        data = browser.download_pdf(url)
    if data is None:
        return None
    path.write_bytes(data)
    return path


def fetch(
    doi: str,
    dest: Path | str = ".",
    resolvers: Sequence[Resolver] | None = None,
) -> FetchResult:
    """Download the PDF and CrossRef metadata for *doi* into *dest*.

    Writes ``<stem>.json`` (when CrossRef has a record) and ``<stem>.pdf`` (when
    a PDF could be located), and returns a :class:`FetchResult` describing what
    happened. A missing CrossRef record is not fatal — PDF resolution is still
    attempted.

    Resolvers are tried in order; each candidate URL is actually downloaded, and
    if a download fails the next resolver is tried. This way a resolver whose
    URL turns out to be undownloadable (e.g. a bot-blocked publisher link) does
    not stop a later resolver (such as the OpenAlex full-text service) from
    succeeding.
    """
    doi = normalize_doi(doi)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    stem = doi_filename(doi)

    json_path: Path | None = None
    try:
        metadata = crossref_metadata(doi)
    except LookupError:
        log.info("no CrossRef metadata for %s", doi)
    else:
        json_path = dest / f"{stem}.json"
        json_path.write_text(json.dumps(metadata, indent=2))

    if resolvers is None:
        resolvers = default_resolvers()

    pdf_path: Path | None = None
    resolver_used: str | None = None
    log.info("looking for a downloadable PDF for %s", doi)
    for resolver in resolvers:
        name = getattr(resolver, "name", type(resolver).__name__)
        log.info("trying resolver: %s", name)
        url = resolver.find_pdf_url(doi)
        if not url:
            continue
        saved = _download_pdf(url, dest / f"{stem}.pdf")
        if saved is not None:
            log.info("saved PDF from %s", name)
            pdf_path = saved
            resolver_used = name
            break
        log.info("could not download from %s; trying next resolver", name)

    if pdf_path is None:
        log.info("no resolver yielded a downloadable PDF for %s", doi)

    return FetchResult(
        doi=doi,
        crossref=json_path is not None,
        json_path=json_path,
        pdf_path=pdf_path,
        resolver=resolver_used,
    )
