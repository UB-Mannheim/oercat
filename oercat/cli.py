"""Command line interface: ``uv run oercat <command>``."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from oercat import export, fetch_vocab
from oercat.reader import read_workbook
from oercat.validate import ERROR, process, render_report

DEFAULT_XLSX = Path("data/oer_catalogue.xlsx")
DEFAULT_SITE = Path("site")


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oercat", description="OER catalogue dashboard builder")
    parser.add_argument("--xlsx", type=Path, default=DEFAULT_XLSX, help="catalogue workbook")
    parser.add_argument("--site", type=Path, default=DEFAULT_SITE, help="Hugo project directory")
    parser.add_argument(
        "--report", type=Path, help="also write the validation report (Markdown) here"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="check the xlsx and print a report")
    p.add_argument("--strict", action="store_true", help="exit with 1 if rows had to be skipped")
    sub.add_parser("build-data", help="validate and write site/data/*.json")
    p = sub.add_parser("serve", help="build data and start a Hugo preview server")
    p.add_argument("--port", type=int, default=1313)
    p = sub.add_parser("build", help="build data and the static site into site/public")
    p.add_argument("--base-url", default="/", help="e.g. https://example.org/oer/")
    sub.add_parser("fetch-vocab", help="refresh discipline labels (needs internet)")

    args = parser.parse_args(argv)

    if args.command == "fetch-vocab":
        print(f"Wrote {fetch_vocab.fetch()} discipline labels.")
        return 0

    wb = read_workbook(args.xlsx)
    records, issues = process(wb)
    report = render_report(issues, len(wb.rows), len(records))
    print(
        report
        if args.command == "validate"
        else render_report(issues, len(wb.rows), len(records), False),
        flush=True,
    )
    if args.report:
        with args.report.open("a", encoding="utf-8") as f:
            f.write(report)

    if args.command == "validate":
        return 1 if args.strict and any(i.severity == ERROR for i in issues) else 0

    oers, vocab = export.export(records, wb, args.xlsx, args.site)
    print(f"Wrote {oers} and {vocab}", flush=True)

    if args.command == "serve":
        return hugo(args.site, "server", "--bind", "0.0.0.0", "--port", str(args.port))
    if args.command == "build":
        return hugo(args.site, "--minify", "--cleanDestinationDir", "--baseURL", args.base_url)
    return 0


def hugo(site: Path, *args: str) -> int:
    venv_hugo = Path(sys.executable).parent / "hugo"
    exe = str(venv_hugo) if venv_hugo.exists() else shutil.which("hugo")
    if not exe:
        print("Hugo not found. Run `uv sync` to install it.", file=sys.stderr)
        return 1
    return subprocess.call([exe, "--source", str(site), *args])
