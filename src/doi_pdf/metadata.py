"""CrossRef metadata lookup."""

from __future__ import annotations

import logging
from typing import Any

import requests

from ._http import DEFAULT_TIMEOUT, USER_AGENT
from .doi import normalize_doi

CROSSREF_API = "https://api.crossref.org/works/"

log = logging.getLogger(__name__)


def crossref_metadata(doi: str) -> dict[str, Any]:
    """Fetch and return the CrossRef work metadata for *doi*.

    Returns the ``message`` object from the CrossRef REST API
    (``https://api.crossref.org/works/{doi}``).

    Raises ``LookupError`` if CrossRef has no record for the DOI.
    """
    doi = normalize_doi(doi)
    url = CROSSREF_API + doi
    log.info("[CrossRef] GET %s", url)
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=DEFAULT_TIMEOUT,
    )
    if resp.status_code == 404:
        raise LookupError(f"no CrossRef record for {doi}")
    resp.raise_for_status()
    message: dict[str, Any] = resp.json()["message"]
    return message
