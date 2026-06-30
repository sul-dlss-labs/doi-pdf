"""Command line entry point for doi-pdf."""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

from .core import FetchResult, fetch
from .doi import normalize_doi
from .resolvers import RESOLVERS, build_resolvers

log = logging.getLogger(__name__)

# A polite default pause between DOIs so batch runs don't hammer the services.
DEFAULT_WAIT_SECONDS = 1.0

# Column header for the --report CSV.
REPORT_COLUMNS = ("doi", "crossref_metadata", "pdf", "resolver")


def _configure_logging(verbose: bool, log_path: str | None) -> None:
    """Route doi_pdf diagnostics to stderr (``--verbose``) and/or a file (``--log``).

    Verbose output to stderr is the bare message; the log file is the same
    information prefixed with a timestamp. Raises ``OSError`` if *log_path*
    cannot be opened.
    """
    if not verbose and not log_path:
        return
    logger = logging.getLogger("doi_pdf")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    if verbose:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(stderr_handler)
    if log_path:
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(file_handler)


def _read_dois(path: str) -> list[str]:
    """Read DOIs from *path* (``-`` for stdin), one per line.

    The first comma-separated field of each line is used, so a CSV export whose
    first column is the DOI works as well as a plain list. Blank lines and ``#``
    comments are skipped, as are lines that do not contain a recognizable DOI
    (e.g. a header row).
    """
    text = sys.stdin.read() if path == "-" else Path(path).read_text()
    dois: list[str] = []
    for line in text.splitlines():
        token = line.split(",", 1)[0].strip()
        if not token or token.startswith("#"):
            continue
        try:
            normalize_doi(token)
        except ValueError:
            log.info("skipping unrecognized DOI: %r", token)
            continue
        dois.append(token)
    return dois


def _report_row(doi: str, result: FetchResult | None) -> dict[str, str]:
    """Build a CSV report row for *doi* from its *result* (``None`` if it errored)."""
    if result is None:
        return {"doi": doi, "crossref_metadata": "no", "pdf": "no", "resolver": ""}
    return {
        "doi": doi,
        "crossref_metadata": "yes" if result.crossref else "no",
        "pdf": "yes" if result.pdf_path else "no",
        "resolver": result.resolver or "",
    }


def _write_report(path: str, rows: list[dict[str, str]]) -> None:
    """Write the per-DOI *rows* to *path* as CSV. Raises ``OSError`` on failure."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``doi-pdf`` CLI.

    Accepts one or more DOIs on the command line and/or via ``--input FILE``.
    Writes ``<stem>.pdf`` and ``<stem>.json`` per DOI into the destination
    directory. Returns 0 when every DOI yielded a PDF, non-zero otherwise.
    """
    parser = argparse.ArgumentParser(
        prog="doi-pdf",
        description="Given a DOI, find an open access PDF and its CrossRef metadata.",
    )
    parser.add_argument(
        "doi",
        nargs="*",
        help="one or more DOIs or DOI URLs (optional if --input is given)",
    )
    parser.add_argument(
        "-i",
        "--input",
        metavar="FILE",
        help="read DOIs from FILE, one per line ('-' for stdin); the first CSV "
        "column is used, so a CSV export works too",
    )
    parser.add_argument(
        "-d",
        "--dest",
        default=".",
        help="directory to write <stem>.pdf and <stem>.json into (default: .)",
    )
    parser.add_argument(
        "-r",
        "--resolver",
        action="append",
        choices=list(RESOLVERS),
        metavar="NAME",
        help=(
            "use only this resolver; repeatable to use several in order. "
            "choices: " + ", ".join(RESOLVERS) + " (default: all, in priority order)"
        ),
    )
    parser.add_argument(
        "-w",
        "--wait",
        type=float,
        default=DEFAULT_WAIT_SECONDS,
        metavar="SECONDS",
        help="seconds to wait between DOIs, to be polite to servers "
        f"(default: {DEFAULT_WAIT_SECONDS}; 0 to disable)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="print which services are queried, at what URLs, and their results",
    )
    parser.add_argument(
        "-l",
        "--log",
        metavar="FILE",
        help="append the verbose diagnostics, timestamped, to FILE",
    )
    parser.add_argument(
        "-c",
        "--report",
        metavar="FILE",
        help="write a CSV report (doi, crossref_metadata, pdf, resolver) to FILE",
    )
    args = parser.parse_args(argv)
    # Pick up OPENALEX_API_KEY (and friends) from a local .env if present.
    load_dotenv()
    try:
        _configure_logging(args.verbose, args.log)
    except OSError as exc:
        parser.error(f"could not open log file {args.log}: {exc}")

    dois = list(args.doi)
    if args.input:
        try:
            dois += _read_dois(args.input)
        except OSError as exc:
            parser.error(f"could not read {args.input}: {exc}")
    if not dois:
        parser.error("provide at least one DOI, or --input FILE")

    resolvers = build_resolvers(args.resolver) if args.resolver else None

    # For a batch, show a progress bar instead of per-DOI output (unless verbose,
    # where the diagnostics stream would clash with the bar).
    show_progress = len(dois) > 1 and not args.verbose

    rows: list[dict[str, str]] = []
    pdf_ok = 0
    no_pdf = 0
    no_meta = 0
    bar = tqdm(total=len(dois), unit="doi", disable=not show_progress)
    try:
        for i, doi in enumerate(dois):
            if i > 0 and args.wait > 0:
                time.sleep(args.wait)
            try:
                result: FetchResult | None = fetch(doi, dest=args.dest, resolvers=resolvers)
            except Exception as exc:  # one bad DOI shouldn't abort the whole batch
                result = None
                message = f"error: {doi}: {exc}"
                bar.write(message) if show_progress else print(message, file=sys.stderr)

            rows.append(_report_row(doi, result))
            if result is not None and result.pdf_path is not None:
                pdf_ok += 1
            else:
                no_pdf += 1
            if result is None or not result.crossref:
                no_meta += 1

            if not show_progress and result is not None:
                if result.json_path is not None:
                    print(f"wrote {result.json_path}")
                if result.pdf_path is not None:
                    print(f"wrote {result.pdf_path}")
                else:
                    print(f"no open access PDF found for {doi}", file=sys.stderr)

            # Show running success/failure tallies on the bar.
            bar.set_postfix({"pdf": pdf_ok, "no-pdf": no_pdf, "no-meta": no_meta})
            bar.update(1)
    finally:
        bar.close()

    failures = no_pdf

    if args.report:
        try:
            _write_report(args.report, rows)
        except OSError as exc:
            parser.error(f"could not write report {args.report}: {exc}")

    if len(dois) > 1:
        print(f"{len(dois) - failures}/{len(dois)} succeeded", file=sys.stderr)
    return 1 if failures else 0
