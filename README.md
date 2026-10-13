# doi-pdf

[![.github/workflows/test.yml](https://github.com/sul-dlss-labs/doi-pdf/actions/workflows/test.yml/badge.svg)](https://github.com/sul-dlss-labs/doi-pdf/actions/workflows/test.yml)

doi-pdf is a command line tool and Python library that, given a DOI, tries to
find an open access PDF for it and downloads the PDF along with the item's
CrossRef metadata. DOIs that CrossRef doesn't know, such as arXiv's
`10.48550/arxiv.*`, get their DataCite metadata instead.

    doi-pdf https://doi.org/10.1371/journal.pone.0234245

writes two files to the current directory, named after the DOI (with `/`
replaced by `-`):

    10.1371-journal.pone.0234245.pdf
    10.1371-journal.pone.0234245.json

The JSON file wraps the agency's native record and says which agency it came
from, since CrossRef and DataCite records have different layouts:

```json
{
  "source": "crossref",
  "record": { "DOI": "10.1371/journal.pone.0234245", "title": ["..."], ... }
}
```

`source` is `crossref` or `datacite`. `record` is CrossRef's work (the
`message` from its REST API) or DataCite's DOI object (the `data` from its
REST API, with the metadata under `attributes`).

The utility currently uses the OpenAlex, Internet Archive Scholar, Web page
extraction to try and locate a PDF. Read on for more details about how
resolution works.

## Requirements

- Python 3.11 or newer.
- **A Chromium browser for [Playwright](https://playwright.dev/python/),
  installed once with `playwright install chromium`** (strongly recommended).
  doi-pdf drives a headless browser for the landing-page resolver and whenever
  a plain HTTP download fails. Without it, doi-pdf still runs and still gets
  every PDF that downloads over plain HTTP, but skips those two steps, so some
  PDFs it could have found are missed; the CLI warns about this at startup.
  The browser goes into Playwright's shared cache (e.g.
  `~/Library/Caches/ms-playwright` on macOS, `~/.cache/ms-playwright` on Linux),
  not into the Python environment, so you only do this once per machine and
  Playwright version.

## Run it without installing

doi-pdf isn't on PyPI yet, so the quickest way to try it is to run it straight
from GitHub with [uv](https://docs.astral.sh/uv/)'s `uvx`. First install the
browser, using the same Playwright version doi-pdf resolves to:

    uvx --from git+https://github.com/sul-dlss-labs/doi-pdf playwright install chromium

uv warns that `playwright` comes from a dependency and suggests
`uvx --from playwright playwright`; ignore that, since it could install a
browser for a different Playwright version than the one doi-pdf uses. Then run
it:

    uvx --from git+https://github.com/sul-dlss-labs/doi-pdf doi-pdf https://doi.org/10.1371/journal.pone.0234245

`uvx` fetches a compatible Python and the dependencies into a temporary
environment and runs the command, with nothing else to install or clean up.

## Install

For repeated use, install it, then install the browser:

    uv pip install git+https://github.com/sul-dlss-labs/doi-pdf
    playwright install chromium

## Command line

### Basic usage

    doi-pdf <doi-or-url> [--dest DIR]

`<doi-or-url>` may be a bare DOI (`10.1371/journal.pone.0234245`), a
`https://doi.org/...` URL, or a `doi:`-prefixed string. `--dest` chooses the
output directory (default: the current directory). The exit code is 0 when a
PDF was downloaded, non-zero otherwise (the metadata JSON is still written).

### Batch processing

Pass several DOIs at once, or read them from a file with `--input` (one DOI per
line; `-` reads stdin). The first comma-separated column of each line is used,
so a CSV export with the DOI in the first column works too; blank lines, `#`
comments, and unrecognized lines (such as a header row) are skipped.

    doi-pdf 10.1371/journal.pone.0234245 10.7554/elife.54129
    doi-pdf --input dois.txt
    cut -d, -f1 export.csv | doi-pdf --input -

By default doi-pdf waits 1 second between DOIs to be polite to the services it
queries. Change it with `--wait SECONDS` (`--wait 0` disables it):

    doi-pdf --input dois.txt --wait 3

When processing more than one DOI, doi-pdf shows a progress bar instead of the
per-DOI output, with running tallies of how many PDFs were retrieved (`pdf`),
came up empty (`no-pdf`), and had no CrossRef or DataCite metadata (`no-meta`):

    50%|█████     | 1/2 [00:05<00:00, pdf=1, no-pdf=0, no-meta=0]

One bad DOI is counted as a failure but does not abort the run; the exit code is
0 only if every DOI produced a PDF.

### CSV report

`--report FILE` writes a CSV summarizing each DOI — where its metadata came
from (`crossref`, `datacite`, or empty if neither has a record), whether a PDF was retrieved, and which resolver retrieved it:

    doi-pdf --input dois.txt --report report.csv

```
doi,metadata,pdf,resolver
10.1371/journal.pone.0234245,crossref,yes,OpenAlex
10.7554/elife.54129,crossref,no,
10.48550/arxiv.1706.03762,datacite,yes,OpenAlex
```

### Choosing resolvers

By default all sources are tried in priority order. `--resolver` restricts to
specific ones; repeat it to use several, in the order given:

    # only Internet Archive Scholar
    doi-pdf --resolver internet-archive 10.1371/journal.pone.0234245

    # OpenAlex first, then Internet Archive Scholar
    doi-pdf --resolver openalex --resolver internet-archive 10.1371/journal.pone.0234245

Resolver names: `openalex`, `internet-archive`, `landing-page`,
`openalex-content` (see below).

### Verbose output

`-v` / `--verbose` logs which services are queried, at what URLs, and what they
return — useful for understanding why a particular DOI did or didn't yield a
PDF:

    doi-pdf -v https://doi.org/10.1371/journal.pone.0234245

### Logging to a file

`--log FILE` appends the same diagnostics to a file, each line prefixed with a
timestamp. It works independently of `--verbose`, so you can keep an audit trail
of a batch run without cluttering the terminal:

    doi-pdf --input dois.txt --log doi-pdf.log

## How it works

doi-pdf separates *finding* a candidate PDF URL from *downloading* the bytes.

**Resolvers** each take a DOI and return a candidate PDF URL (or nothing). They
are tried in order, free sources first:

1. `openalex` — the open access locations OpenAlex already knows about
   (`best_oa_location` and friends).
2. `internet-archive` — a preserved fulltext copy in
   [Internet Archive Scholar](https://scholar.archive.org/).
3. `landing-page` — resolve the DOI to the publisher page, render it in a
   headless browser, and scrape a PDF link (e.g. `citation_pdf_url`).
4. `openalex-content` — OpenAlex's paid full-text service, used only as a last
   resort (see below).

**The downloader** turns a candidate URL into PDF bytes. It first tries a plain
HTTP request; if that is refused, or the URL turns out to be an HTML *viewer*
page that merely embeds the PDF (as many institutional repositories and OJS
journals do), it retries with a headless browser and extracts the embedded PDF.

**`fetch` ties the two together with fall-through:** it tries each resolver,
actually downloads the candidate, and if the download fails it moves on to the
next resolver. So a resolver whose URL turns out to be undownloadable (a
bot-blocked publisher link) does not stop a later resolver from succeeding.

> Some publishers (e.g. SAGE) front their PDFs with aggressive bot protection
> (Cloudflare managed challenges) that blocks headless browsers too, so a PDF
> cannot always be retrieved even when one exists. doi-pdf does not attempt to
> defeat such protections.

### OpenAlex full-text service

If `OPENALEX_API_KEY` is set, doi-pdf will use OpenAlex's full-text PDF service
as a **last resort** — only after the free sources fail to produce a
downloadable PDF. For works OpenAlex holds the full text for (`has_content.pdf`)
it fetches the PDF from `content.openalex.org`. This is a paid OpenAlex feature
(about \$0.01 per download). Without a key the service is skipped entirely.

The key is read from the environment, or from a local `.env` file (loaded
automatically by the CLI):

    OPENALEX_API_KEY=your-key-here
    OPENALEX_MAILTO=you@example.org   # optional, for the OpenAlex polite pool

See https://developers.openalex.org/download/full-text-pdfs for details.

## Using it as a library

The high-level entry point mirrors the CLI:

```python
from doi_pdf import fetch

# Writes <stem>.pdf (when found) and <stem>.json ({"source": ..., "record": ...},
# the CrossRef record, or the DataCite record when CrossRef has none) into dest,
# and returns a FetchResult describing what happened.
result = fetch(
    "https://doi.org/10.1371/journal.pone.0234245",
    dest="downloads",
)
if result.pdf_path:
    print(f"saved {result.pdf_path} via {result.resolver}")
else:
    print("no PDF found")
print(f"metadata from: {result.metadata}")  # "crossref", "datacite", or None
```

`FetchResult` has `doi`, `metadata` (`"crossref"`, `"datacite"`, or `None`),
`crossref` (bool, true when the metadata came from CrossRef), `json_path`, `pdf_path`, and
`resolver` (the name of the resolver that produced the PDF, or `None`).

Restrict or reorder the sources with `build_resolvers`, or pass your own list:

```python
from doi_pdf import build_resolvers, fetch

resolvers = build_resolvers(["openalex", "internet-archive"])
result = fetch("10.1371/journal.pone.0234245", resolvers=resolvers)
```

Lower-level pieces are available too:

```python
from doi_pdf import crossref_metadata, datacite_metadata, find_pdf_url, normalize_doi

normalize_doi("https://doi.org/10.1371/JOURNAL.pone.0234245")
# -> "10.1371/journal.pone.0234245"

find_pdf_url("10.1371/journal.pone.0234245")
# -> "https://journals.plos.org/.../article/file?...&type=printable" (or None)

meta = crossref_metadata("10.1371/journal.pone.0234245")
meta["title"]

meta = datacite_metadata("10.48550/arxiv.1706.03762")
meta["attributes"]["titles"]
```

Resolvers emit diagnostics on the `doi_pdf` logger at `INFO`; configure logging
to see them. To use the OpenAlex full-text service from library code, set
`OPENALEX_API_KEY` in the environment (the CLI loads `.env` for you; a library
process should load it itself or set the variable).

## Contributing

Lint, format, and type-check with:

    uv run ruff check
    uv run ruff format
    uv run ty check

CI runs these along with the offline test subset on every PR. See
[AGENTS.md](AGENTS.md) for development setup, the test layout, and the project
conventions.
