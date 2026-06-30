# Contributing to doi-pdf

doi-pdf is a small CLI + library that, given a DOI, finds an open access PDF and
downloads it alongside the item's CrossRef metadata. This file is for humans and
coding agents who want to work on it.

## Setup

The project uses [uv](https://docs.astral.sh/uv/) and targets Python 3.15
(pinned in `.python-version`).

```sh
uv venv                              # create the virtualenv
uv pip install -e '.[dev]'           # install the package + dev tools
uv run playwright install chromium   # browser used by the landing-page resolver
```

## Common commands

```sh
uv run pytest                        # run the whole test suite
uv run pytest -m "not network and not browser"   # fast, offline tests only
uv run ruff check                    # lint
uv run ruff format                   # auto-format (use --check in CI)
uv run ty check                      # type check (src + tests)
uv run doi-pdf -v 10.1371/journal.pone.0234245   # run the CLI
uv run doi-pdf --input dois.txt --wait 2          # batch from a file
```

Linting and formatting use [ruff](https://docs.astral.sh/ruff/); type checking
uses [ty](https://github.com/astral-sh/ty). There is no mypy or black. CI
(`.github/workflows/test.yml`) runs `ruff check`, `ruff format --check`,
`ty check`, and the offline test subset on every PR.

The CLI takes one or more DOIs and/or `--input FILE` (one DOI per line; first CSV
column; `-` for stdin), writes `<stem>.pdf`/`<stem>.json` per DOI, and pauses
`--wait` seconds between DOIs (default 1.0) to be polite. For more than one DOI
it shows a tqdm progress bar instead of per-DOI output. `--report FILE` writes a
CSV (`doi, crossref_metadata, pdf, resolver`); `--log FILE` writes timestamped
diagnostics. `fetch()` returns a `FetchResult` (`doi`, `crossref`, `json_path`,
`pdf_path`, `resolver`).

Type checking is done with [ty](https://github.com/astral-sh/ty); there is no
mypy. Everything in `src/` and `tests/` is fully type annotated — keep it that
way (annotate new functions, methods, and test helpers).

## Layout

```
src/doi_pdf/
  doi.py        normalize_doi(), doi_filename() — DOI parsing (pure, no I/O)
  metadata.py   crossref_metadata() — CrossRef lookup
  resolvers.py  the pluggable resolvers + the RESOLVERS registry
  browser.py    headless-browser PDF download / embedded-PDF extraction
  core.py       find_pdf_url() and fetch() — coordination + download
  cli.py        the `doi-pdf` command
  _http.py      shared User-Agents, timeout, and redact() for secrets
tests/          pytest tests; conftest.py loads a local .env
```

## Architecture

The central design split (please preserve it):

- **Resolvers find a candidate PDF *URL*.** Each implements
  `find_pdf_url(doi) -> str | None` and a `name`. They are tried in order. To add
  a new way of *finding* a PDF, write a resolver and register it in `RESOLVERS`.
- **The downloader turns a URL into PDF *bytes*.** `core._download_pdf` tries a
  plain HTTP GET, then falls back to a headless browser (`browser.download_pdf`),
  which also extracts PDFs embedded in HTML viewer pages (e.g. eScholarship). To
  add a new way of *retrieving* bytes from a stubborn URL, extend the downloader,
  not the resolvers.
- **`fetch()` drives both with fall-through.** It tries each resolver and
  actually downloads the candidate; if a download fails it moves to the next
  resolver, so an undownloadable URL (a bot-blocked publisher link) never blocks
  a later resolver from succeeding.

Default resolver order (free first, paid last):
`openalex` → `internet-archive` → `landing-page` → `openalex-content`. The CLI
`--resolver NAME` flag (repeatable) restricts/reorders this; `build_resolvers()`
builds a list from short names in `RESOLVERS`.

Known limit: publishers behind aggressive bot protection (Cloudflare managed
challenges, e.g. SAGE) block headless Chromium too, so some PDFs can't be
retrieved. We deliberately do **not** add stealth/evasion tooling.

## Configuration & secrets

- `OPENALEX_API_KEY` enables the paid OpenAlex full-text service
  (`openalex-content`, \$0.01 per download), tried only as a last resort.
- `OPENALEX_MAILTO` (optional) is sent to OpenAlex for the polite pool.

These are read from the environment or a local `.env` (loaded via python-dotenv
in the CLI and in `tests/conftest.py`). **Never commit `.env`** — it is
gitignored. The API key rides in the content-service URL, so any URL that gets
logged is passed through `_http.redact()`; use it when logging URLs.

## Tests

Live tests hit real services on purpose (no HTTP mocking). They are marked so you
can skip them:

- `@pytest.mark.network` — makes live network calls.
- `@pytest.mark.browser` — drives headless Chromium (slow; needs the
  `playwright install` step above).

Run the fast subset with `-m "not network and not browser"` while iterating.
Tests that exercise the OpenAlex full-text service are gated with
`@pytest.mark.skipif(not os.environ.get("OPENALEX_API_KEY"))`, so they only run
when a key is available and otherwise skip. When asserting on URLs that contain
the key, assert on shape (`"api_key=" in url`) rather than echoing its value.

## Conventions

- Match the surrounding style; keep functions annotated and `uv run ruff check`,
  `uv run ruff format --check`, and `uv run ty check` clean.
- Resolvers and the downloader emit diagnostics on the `doi_pdf` logger at
  `INFO`; the CLI's `--verbose` flag turns these on. Log the service, the URL
  (redacted), and the result.
- Prefer real, stable open access DOIs when adding live tests (gold-OA PLOS /
  eLife articles are reliable).
