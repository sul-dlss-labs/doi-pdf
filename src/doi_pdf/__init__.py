"""doi-pdf: given a DOI, find an open access PDF and its CrossRef metadata."""

from __future__ import annotations

from .core import FetchResult, fetch, find_pdf_url
from .doi import doi_filename, normalize_doi
from .metadata import crossref_metadata
from .resolvers import (
    RESOLVERS,
    InternetArchiveScholarResolver,
    LandingPageResolver,
    OpenAlexContentResolver,
    OpenAlexResolver,
    Resolver,
    build_resolvers,
    default_resolvers,
)

__all__ = [
    "normalize_doi",
    "doi_filename",
    "crossref_metadata",
    "Resolver",
    "OpenAlexResolver",
    "OpenAlexContentResolver",
    "InternetArchiveScholarResolver",
    "LandingPageResolver",
    "RESOLVERS",
    "build_resolvers",
    "default_resolvers",
    "find_pdf_url",
    "fetch",
    "FetchResult",
]
