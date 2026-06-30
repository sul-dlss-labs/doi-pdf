"""DOI parsing and normalization helpers."""

from __future__ import annotations

import re

# A DOI is "10." followed by a registrant code and a "/" and a suffix.
_DOI_RE = re.compile(r"10\.\d{4,9}/\S+")

# Leading junk we strip before matching: a "doi:" scheme or a doi.org URL.
_PREFIX_RE = re.compile(r"^(doi:|https?://(dx\.)?doi\.org/)", re.IGNORECASE)


def normalize_doi(value: str) -> str:
    """Return the bare DOI for *value*.

    Accepts a bare DOI (``10.1177/13548565231164759``), an ``https://doi.org/``
    URL, a ``doi:`` prefixed string, etc., and returns the canonical bare DOI
    in lower case.

    Raises ``ValueError`` if *value* does not contain a recognizable DOI.
    """
    if not isinstance(value, str):
        raise ValueError(f"not a DOI: {value!r}")
    text = _PREFIX_RE.sub("", value.strip()).strip()
    if not _DOI_RE.fullmatch(text):
        raise ValueError(f"not a DOI: {value!r}")
    return text.lower()


def doi_filename(doi: str) -> str:
    """Return a filesystem-safe stem for *doi*.

    ``10.1177/13548565231164759`` -> ``10.1177-13548565231164759`` so that it
    can be used as ``<stem>.pdf`` / ``<stem>.json``.
    """
    return normalize_doi(doi).replace("/", "-")
