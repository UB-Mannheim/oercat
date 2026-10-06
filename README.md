# OER-Katalog Dashboard

A static, bilingual (DE/EN) web dashboard for browsing Open Educational Resources on
AI and data literacy. It offers full-text search, filters for every catalogue column,
and one detail page per OER.

The only data source is **`data/oer_catalogue.xlsx`** (DALIA metadata schema).

## Add a new OER

1. Open `data/oer_catalogue.xlsx` and append a row to the table. Give it the next free
   number in `No`, and follow the `Explanation` sheet.
2. Run `uv run oercat validate`. The report lists every problem by Excel row and column.
3. Run `uv run oercat serve` and check the result at http://localhost:1313.
4. Commit the xlsx.

The number in `No` becomes the page address (`/de/oer/<No>/`), so never reuse or change it.

## Setup

You only need [uv](https://docs.astral.sh/uv/). It installs Python dependencies **and Hugo**
(pinned in `uv.lock`):

```bash
uv sync
```

## Commands

| Command                                  | What it does                                                         |
|------------------------------------------|----------------------------------------------------------------------|
| `uv run oercat validate`                 | Check the xlsx, print a report. `--strict` exits 1 if rows are skipped. |
| `uv run oercat serve`                    | Build data + start a live preview on port 1313                       |
| `uv run oercat build`                    | Build the static site into `site/public/`                            |
| `uv run oercat build --base-url /path/`  | Same, for hosting under a sub-path (e.g. GitHub Pages project sites) |
| `uv run oercat build-data`               | Only regenerate `site/data/*.json`                                   |
| `uv run oercat fetch-vocab`              | Refresh discipline labels (Hochschulfächersystematik; needs internet) |
| `uv run pytest` / `uv run ruff check .`  | Tests / lint                                                         |

Global options: `--xlsx <file>`, `--site <dir>`, `--report <file>` (writes the full report as Markdown).

## How it works

```
data/oer_catalogue.xlsx
  └─ oercat (Python): read → normalize → validate → site/data/oers.json + vocab.json
       └─ Hugo: search page, /oer/<No>/ detail pages, /<lang>/index.json search index
            └─ browser: search.js + MiniSearch, full-text search and filters, all client-side
```

- **Python** (`oercat/`) handles the messy parts:
  - It splits ` * ` multi-value cells and parses authors with ORCID/ROR.
  - It maps picklist values to their canonical form, ignoring case and punctuation.
  - It turns discipline URIs into labels and finds broken rows.

  Bad cells never stop the build. The value is dropped and reported instead.
- **Hugo** (`site/`) uses a content adapter (`site/content-shared/oer/_content.gotmpl`) to create
  the detail pages straight from the JSON. No Markdown files are generated.
- **JavaScript** (`site/assets/js/search.js`) is one plain file with no framework and no npm.
  Filter state lives in the URL, so every filtered view can be shared as a link.

### Where to change what

| Task                                        | File(s)                                              |
|---------------------------------------------|------------------------------------------------------|
| Add/remove a column or filter               | `oercat/schema.py` + `facet_<key>` in `site/i18n/*.yaml` |
| Fix a recurring misspelling in the xlsx     | `oercat/vocab/aliases.yaml`                          |
| Translate a vocabulary value (e.g. Lecture) | `oercat/vocab/labels.yaml`                           |
| UI texts                                    | `site/i18n/de.yaml`, `site/i18n/en.yaml`             |
| Colours, spacing, layout                    | `site/assets/css/main.css` (tokens at the top)       |
| Search page / detail page markup            | `site/layouts/home.html`, `site/layouts/oer/page.html` |

### Third-party code

`site/assets/js/vendor/minisearch.js` is [MiniSearch](https://github.com/lucaong/minisearch) 7.2.0
(MIT License).
