# OERcat 😺

[OERcat](https://ub-mannheim.github.io/oercat/en/) is a web dashboard that allows users to search for and filter open educational resources (OER) related to AI and data literacy.

## Pipeline

OER metadata is maintained in a single Excel file (`data/AiDaLi_OER_Katalog.xlsx`) that follows the [DALIA Interchange Format (DIF V1.4)](https://doi.org/10.5281/zenodo.17871138) metadata schema.

A Python pipeline (`uv run oercat build`) reads the spreadsheet, normalizes and validates each row, and exports the result as JSON. [Hugo](https://gohugo.io) turns that data into a static, bilingual (DE/EN) site with a client-side search and filter page and a detail page for every resource. The site is built and deployed automatically via GitHub Actions.

### Installation

The project uses [uv](https://docs.astral.sh/uv/) and Python 3.13. Hugo is installed into the virtual environment automatically.

```bash
git clone https://github.com/tsmdt/oercat.git
cd oercat
uv sync                  # install dependencies (incl. Hugo)
uv run oercat validate   # check the Excel file
uv run oercat serve      # live preview at http://localhost:1313
uv run oercat build      # full static build into site/public/
```



## Funding

`OERcat` is a project outcome of [AiDaLi: Promoting AI and Data Literacy Through OER Production](https://transferkiosk.net/p/102025-durch-oer-produktion-zu-ai-und) (2026-2028), funded by [Stiftung Innovation in der Hochschullehre](https://stiftung-hochschullehre.de/en/).

## Acknowledgement

Claude Sonnet 5 and Opus 5 helped to create this app.
