"""CrossRef and DataCite metadata lookup."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import requests

from ._http import DEFAULT_TIMEOUT, USER_AGENT, redact
from .doi import normalize_doi

CROSSREF_API = "https://api.crossref.org/works/"
DATACITE_API = "https://api.datacite.org/dois/"

log = logging.getLogger(__name__)


class MetadataResponseError(Exception):
    """A registration agency answered, but not with a usable record."""


def _get_record(api: str, envelope: str, agency: str, doi: str) -> dict[str, Any]:
    """GET *doi* from a registration agency's REST *api* and unwrap *envelope*.

    The DOI is percent-encoded into the URL path: DOIs may contain ``#``, ``?``
    and similar characters (e.g. Wiley SICI DOIs ending in ``#``) that would
    otherwise truncate the URL and fetch the wrong record, or none.

    Raises ``LookupError`` only when the agency has no record (HTTP 404).
    Other failures are not ``LookupError``: ``requests.RequestException`` for
    transport and HTTP errors and for a body that is not JSON, and
    :class:`MetadataResponseError` for JSON that lacks the *envelope* object.
    """
    doi = normalize_doi(doi)
    url = api + quote(doi, safe="/")
    log.info("[%s] GET %s", agency, redact(url))
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code == 404:
        raise LookupError(f"no {agency} record for {doi}")
    resp.raise_for_status()
    body = resp.json()
    if not isinstance(body, dict) or not isinstance(body.get(envelope), dict):
        raise MetadataResponseError(
            f"unexpected {agency} response for {doi}: no {envelope!r} object"
        )
    record: dict[str, Any] = body[envelope]
    return record


def crossref_metadata(doi: str) -> dict[str, Any]:
    """Fetch and return the CrossRef work metadata for *doi*.

    Returns the ``message`` object from the CrossRef REST API
    (``https://api.crossref.org/works/{doi}``).

    Raises ``LookupError`` if CrossRef has no record for the DOI.
    """
    return _get_record(CROSSREF_API, "message", "CrossRef", doi)


def datacite_metadata(doi: str) -> dict[str, Any]:
    """Fetch and return the DataCite metadata for *doi*.

    Returns the ``data`` object from the DataCite REST API
    (``https://api.datacite.org/dois/{doi}``). DataCite registers DOIs that
    CrossRef does not, such as arXiv's ``10.48550/arxiv.*`` and many datasets.

    Raises ``LookupError`` if DataCite has no record for the DOI.
    """
    return _get_record(DATACITE_API, "data", "DataCite", doi)
