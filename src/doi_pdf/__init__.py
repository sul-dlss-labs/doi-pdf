"""doi-pdf: given a DOI, find an open access PDF and its CrossRef or DataCite metadata."""

from __future__ import annotations

import logging

from .core import FetchResult, fetch, find_pdf_url
from .doi import doi_filename, normalize_doi
from .metadata import MetadataResponseError, crossref_metadata, datacite_metadata
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

# A library leaves logging output to the application: diagnostics appear only
# when a handler is configured (the CLI's --verbose / --log), never through
# logging's last-resort stderr handler.
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "RESOLVERS",
    "FetchResult",
    "InternetArchiveScholarResolver",
    "LandingPageResolver",
    "MetadataResponseError",
    "OpenAlexContentResolver",
    "OpenAlexResolver",
    "Resolver",
    "build_resolvers",
    "crossref_metadata",
    "datacite_metadata",
    "default_resolvers",
    "doi_filename",
    "fetch",
    "find_pdf_url",
    "normalize_doi",
]
