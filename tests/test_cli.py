"""Tests for the doi-pdf command line interface."""

import logging
import os
import re
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from doi_pdf import FetchResult, cli
from doi_pdf.cli import _read_dois, main


@pytest.fixture
def reset_doi_pdf_logging() -> Iterator[None]:
    """Detach any handlers configured on the doi_pdf logger after the test."""
    yield
    logger = logging.getLogger("doi_pdf")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    logger.setLevel(logging.NOTSET)


def test_main_requires_a_doi_argument() -> None:
    # No DOI and no --input should exit (SystemExit) via parser.error.
    with pytest.raises(SystemExit):
        main([])


def test_main_rejects_unknown_resolver() -> None:
    # An invalid --resolver choice should be rejected by argparse.
    with pytest.raises(SystemExit):
        main(["10.1234/abc", "--resolver", "nope"])


def test_read_dois_skips_blanks_comments_and_junk(tmp_path: Path) -> None:
    f = tmp_path / "dois.txt"
    f.write_text(
        "# a comment\n"
        "10.1371/journal.pone.0234245\n"
        "\n"
        "https://doi.org/10.7554/elife.54129\n"
        "not-a-doi\n"
    )
    assert _read_dois(str(f)) == [
        "10.1371/journal.pone.0234245",
        "https://doi.org/10.7554/elife.54129",
    ]


def test_read_dois_uses_first_csv_column(tmp_path: Path) -> None:
    f = tmp_path / "export.csv"
    f.write_text("doi,pub_year\n10.1371/journal.pone.0234245,2020\n,1999\n")
    # Header ("doi") and the empty-DOI row are skipped; the real DOI is kept.
    assert _read_dois(str(f)) == ["10.1371/journal.pone.0234245"]


def test_main_processes_multiple_dois_with_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fetched: list[str] = []

    def fake_fetch(
        doi: str, dest: Path | str = ".", resolvers: Sequence[object] | None = None
    ) -> FetchResult:
        fetched.append(doi)
        return FetchResult(doi, True, Path(dest) / "x.json", None, None)

    slept: list[float] = []
    monkeypatch.setattr(cli, "fetch", fake_fetch)
    monkeypatch.setattr(cli.time, "sleep", lambda s: slept.append(s))

    code = main(
        [
            "10.1371/journal.pone.0234245",
            "10.7554/elife.54129",
            "--dest",
            str(tmp_path),
            "--wait",
            "2.5",
        ]
    )

    assert fetched == ["10.1371/journal.pone.0234245", "10.7554/elife.54129"]
    assert slept == [2.5]  # exactly one pause, between the two DOIs
    assert code == 1  # both returned no PDF


def test_no_headless_flag_sets_browser_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--no-headless asks the browser fallback to run headful via its env var."""
    monkeypatch.delenv("DOI_PDF_HEADLESS", raising=False)

    def fake_fetch(
        doi: str, dest: Path | str = ".", resolvers: Sequence[object] | None = None
    ) -> FetchResult:
        return FetchResult(doi, True, Path(dest) / "x.json", None, None)

    monkeypatch.setattr(cli, "fetch", fake_fetch)

    main(["10.1371/journal.pone.0234245", "--dest", str(tmp_path), "--no-headless"])
    assert os.environ["DOI_PDF_HEADLESS"] == "0"


def test_without_no_headless_flag_env_is_left_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DOI_PDF_HEADLESS", raising=False)

    def fake_fetch(
        doi: str, dest: Path | str = ".", resolvers: Sequence[object] | None = None
    ) -> FetchResult:
        return FetchResult(doi, True, Path(dest) / "x.json", None, None)

    monkeypatch.setattr(cli, "fetch", fake_fetch)

    main(["10.1371/journal.pone.0234245", "--dest", str(tmp_path)])
    assert "DOI_PDF_HEADLESS" not in os.environ


def test_main_reads_dois_from_input_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f = tmp_path / "dois.txt"
    f.write_text("10.1371/journal.pone.0234245\n")
    fetched: list[str] = []

    def fake_fetch(
        doi: str, dest: Path | str = ".", resolvers: Sequence[object] | None = None
    ) -> FetchResult:
        fetched.append(doi)
        return FetchResult(doi, True, Path(dest) / "x.json", Path(dest) / "x.pdf", "OpenAlex")

    monkeypatch.setattr(cli, "fetch", fake_fetch)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)

    code = main(["--input", str(f), "--dest", str(tmp_path)])
    assert fetched == ["10.1371/journal.pone.0234245"]
    assert code == 0


def test_main_log_option_writes_timestamped_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reset_doi_pdf_logging: None
) -> None:
    log_file = tmp_path / "run.log"

    def fake_fetch(
        doi: str, dest: Path | str = ".", resolvers: Sequence[object] | None = None
    ) -> FetchResult:
        logging.getLogger("doi_pdf.core").info("looking for a PDF for %s", doi)
        return FetchResult(doi, True, Path(dest) / "x.json", None, None)

    monkeypatch.setattr(cli, "fetch", fake_fetch)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)

    # --log without --verbose still captures the diagnostics.
    main(["10.1371/journal.pone.0234245", "--dest", str(tmp_path), "--log", str(log_file)])

    text = log_file.read_text()
    assert "looking for a PDF for 10.1371/journal.pone.0234245" in text
    # Each line is prefixed with a timestamp (YYYY-MM-DD HH:MM:SS).
    assert re.search(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", text)


def test_main_log_option_reports_bad_path(tmp_path: Path, reset_doi_pdf_logging: None) -> None:
    # A directory that does not exist should fail cleanly via parser.error.
    bad = tmp_path / "missing-dir" / "run.log"
    with pytest.raises(SystemExit):
        main(["10.1234/abc", "--log", str(bad)])


def test_main_writes_csv_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import csv

    # doi -> (crossref?, has_pdf?, resolver)
    outcomes = {
        "10.1234/aaa": FetchResult(
            "10.1234/aaa", True, tmp_path / "a.json", tmp_path / "a.pdf", "OpenAlex"
        ),
        "10.1234/bbb": FetchResult("10.1234/bbb", True, tmp_path / "b.json", None, None),
        "10.1234/ccc": FetchResult(
            "10.1234/ccc", False, None, tmp_path / "c.pdf", "Internet Archive Scholar"
        ),
    }

    def fake_fetch(
        doi: str, dest: Path | str = ".", resolvers: Sequence[object] | None = None
    ) -> FetchResult:
        return outcomes[doi]

    monkeypatch.setattr(cli, "fetch", fake_fetch)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)

    report = tmp_path / "report.csv"
    main([*outcomes, "--dest", str(tmp_path), "--report", str(report)])

    with report.open(newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert [r["doi"] for r in rows] == list(outcomes)
    by_doi = {r["doi"]: r for r in rows}
    assert by_doi["10.1234/aaa"] == {
        "doi": "10.1234/aaa",
        "crossref_metadata": "yes",
        "pdf": "yes",
        "resolver": "OpenAlex",
    }
    assert by_doi["10.1234/bbb"]["pdf"] == "no"
    assert by_doi["10.1234/bbb"]["resolver"] == ""
    assert by_doi["10.1234/ccc"]["crossref_metadata"] == "no"
    assert by_doi["10.1234/ccc"]["resolver"] == "Internet Archive Scholar"


@pytest.mark.network
@pytest.mark.browser
def test_main_writes_files_into_dest(tmp_path: Path) -> None:
    exit_code = main(["10.1371/journal.pone.0234245", "--dest", str(tmp_path)])
    assert exit_code == 0
    assert (tmp_path / "10.1371-journal.pone.0234245.json").exists()
