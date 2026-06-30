"""Live test for the headless-browser PDF download fallback."""

import pytest

from doi_pdf import browser

pytestmark = [pytest.mark.network, pytest.mark.browser]

# A gold-OA PLOS article whose PDF a browser can fetch directly.
PLOS_PDF = (
    "https://journals.plos.org/plosone/article/file?id=10.1371/journal.pone.0234245&type=printable"
)


def test_download_pdf_returns_pdf_bytes() -> None:
    data = browser.download_pdf(PLOS_PDF)
    assert data is not None
    assert data.startswith(b"%PDF")


def test_download_pdf_returns_none_for_non_pdf() -> None:
    # A normal HTML page is not a PDF, so the fallback should decline it.
    assert browser.download_pdf("https://example.com/") is None


# An eScholarship item page is an HTML viewer that embeds the PDF rather than
# serving it directly; the browser fallback should still extract the file.
ESCHOLARSHIP_VIEWER = "https://escholarship.org/uc/item/4vk4m26c"


def test_download_pdf_extracts_pdf_embedded_in_viewer_page() -> None:
    data = browser.download_pdf(ESCHOLARSHIP_VIEWER)
    assert data is not None
    assert data.startswith(b"%PDF")
