# doi-pdf

doi-pdf is a command line tool and Python library that, given a DOI, tries to
find an open access PDF for it and downloads the PDF along with the item's
CrossRef metadata.

    doi-pdf https://doi.org/10.1371/journal.pone.0234245

writes two files to the current directory, named after the DOI (with `/`
replaced by `-`):

    10.1371-journal.pone.0234245.pdf
    10.1371-journal.pone.0234245.json

The utility currently uses the OpenAlex, Internet Archive Scholar, Web page
extraction to try and locate a PDF. Read on for more details about how
resolution works.

## Run it without installing

doi-pdf isn't on PyPI yet, so the quickest way to try it is to run it straight
from GitHub with [uv](https://docs.astral.sh/uv/)'s `uvx`:

    uvx --from git+https://github.com/sul-dlss-labs/doi-pdf doi-pdf https://doi.org/10.1371/journal.pone.0234245

`uvx` fetches a compatible Python and the dependencies into a temporary
environment and runs the `doi-pdf` command — nothing to install or clean up. The
OpenAlex and Internet Archive resolvers work out of the box; the landing-page
resolver and the headless-browser download fallback additionally need a one-time
`playwright install chromium` (see below).

## Install

For repeated use, install it (doi-pdf needs Python 3.15+):

    uv pip install git+https://github.com/sul-dlss-labs/doi-pdf

The publisher-landing-page resolver and the browser download fallback drive a
headless browser, so install one once:

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
came up empty (`no-pdf`), and lacked CrossRef metadata (`no-meta`):

    50%|█████     | 1/2 [00:05<00:00, pdf=1, no-pdf=0, no-meta=0]

One bad DOI is counted as a failure but does not abort the run; the exit code is
0 only if every DOI produced a PDF.

### CSV report

`--report FILE` writes a CSV summarizing each DOI — whether CrossRef metadata
was found, whether a PDF was retrieved, and which resolver retrieved it:

    doi-pdf --input dois.txt --report report.csv

```
doi,crossref_metadata,pdf,resolver
10.1371/journal.pone.0234245,yes,yes,OpenAlex
10.7554/elife.54129,yes,no,
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
page that merely embeds the PDF (as many institutional repositories do, e.g.
eScholarship), it retries with a headless browser and extracts the embedded
PDF.

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

# Writes <stem>.pdf (when found) and <stem>.json (when CrossRef has a record)
# into dest, and returns a FetchResult describing what happened.
result = fetch(
    "https://doi.org/10.1371/journal.pone.0234245",
    dest="downloads",
)
if result.pdf_path:
    print(f"saved {result.pdf_path} via {result.resolver}")
else:
    print("no PDF found")
print(f"CrossRef metadata available: {result.crossref}")
```

`FetchResult` has `doi`, `crossref` (bool), `json_path`, `pdf_path`, and
`resolver` (the name of the resolver that produced the PDF, or `None`).

Restrict or reorder the sources with `build_resolvers`, or pass your own list:

```python
from doi_pdf import build_resolvers, fetch

resolvers = build_resolvers(["openalex", "internet-archive"])
result = fetch("10.1371/journal.pone.0234245", resolvers=resolvers)
```

Lower-level pieces are available too:

```python
from doi_pdf import find_pdf_url, crossref_metadata, normalize_doi

normalize_doi("https://doi.org/10.1371/JOURNAL.pone.0234245")
# -> "10.1371/journal.pone.0234245"

find_pdf_url("10.1371/journal.pone.0234245")
# -> "https://journals.plos.org/.../article/file?...&type=printable" (or None)

meta = crossref_metadata("10.1371/journal.pone.0234245")
meta["title"]
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
