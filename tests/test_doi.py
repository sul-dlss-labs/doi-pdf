"""Pure-logic tests for DOI normalization and filename derivation.

These need no network and should always run fast.
"""

import pytest

from doi_pdf import doi_filename, normalize_doi

# Real-world DOIs plus the example in the README.
README_DOI = "10.1177/13548565231164759"


@pytest.mark.parametrize(
    "value",
    [
        "10.1177/13548565231164759",
        "https://doi.org/10.1177/13548565231164759",
        "http://doi.org/10.1177/13548565231164759",
        "https://dx.doi.org/10.1177/13548565231164759",
        "http://dx.doi.org/10.1177/13548565231164759",
        "doi:10.1177/13548565231164759",
        "  10.1177/13548565231164759  ",
    ],
)
def test_normalize_doi_accepts_common_forms(value: str) -> None:
    assert normalize_doi(value) == README_DOI


def test_normalize_doi_is_case_insensitive() -> None:
    # DOIs are case-insensitive; we canonicalize to lower case.
    assert normalize_doi("10.1371/JOURNAL.PONE.0234245") == "10.1371/journal.pone.0234245"


@pytest.mark.parametrize(
    "doi",
    [
        "10.1016/j.molcel.2009.06.021",
        "10.1038/s41388-019-1077-y",
        "10.48550/arxiv.1411.1134",
        "10.1016/s2666-6367(23)00280-4",  # parentheses in the suffix
    ],
)
def test_normalize_doi_roundtrips_bare_dois(doi: str) -> None:
    assert normalize_doi(doi) == doi


@pytest.mark.parametrize("value", ["", "   ", "not-a-doi", "https://example.com/foo"])
def test_normalize_doi_rejects_garbage(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_doi(value)


def test_doi_filename_matches_readme_example() -> None:
    assert doi_filename(README_DOI) == "10.1177-13548565231164759"


@pytest.mark.parametrize(
    "doi,stem",
    [
        ("10.1371/journal.pone.0234245", "10.1371-journal.pone.0234245"),
        ("10.7554/elife.54129", "10.7554-elife.54129"),
        ("10.48550/arxiv.1411.1134", "10.48550-arxiv.1411.1134"),
    ],
)
def test_doi_filename_replaces_slashes(doi: str, stem: str) -> None:
    assert doi_filename(doi) == stem


def test_doi_filename_accepts_url_form() -> None:
    # Should normalize first, so a URL produces the same stem as the bare DOI.
    assert doi_filename(f"https://doi.org/{README_DOI}") == "10.1177-13548565231164759"
