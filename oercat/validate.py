from collections import Counter
from dataclasses import dataclass

from oercat.normalize import PARSERS, Context, is_placeholder
from oercat.reader import Workbook
from oercat.schema import COLUMNS

ERROR, WARNING = "error", "warning"
SHIFTED_ROW_MIN_HEADER_CELLS = 3


@dataclass
class Issue:
    excel_row: int
    column: str
    severity: str  # ERROR: row skipped, WARNING: row kept, value dropped
    message: str


def process(wb: Workbook) -> tuple[list[dict], list[Issue]]:
    issues: list[Issue] = []
    records: list[dict] = []

    missing = [c.header for c in COLUMNS if c.header not in wb.headers]
    for header in missing:
        issues.append(Issue(1, header, WARNING, "column not found in the sheet"))

    header_names = set(wb.headers)
    for row in wb.rows:
        # A row whose cells contain column names was shifted during copy & paste.
        header_like = [h for h, v in row.cells.items() if v in header_names]
        if len(header_like) >= SHIFTED_ROW_MIN_HEADER_CELLS:
            issues.append(Issue(row.excel_row, "*", ERROR,
                                f"cells contain column names ({', '.join(header_like[:4])}, …); "
                                "columns look shifted → row skipped"))  # fmt: skip
            continue

        record, row_issues = process_row(row.excel_row, row.cells, wb.picklists)
        issues.extend(row_issues)
        if not any(i.severity == ERROR for i in row_issues):
            records.append(record)

    issues.extend(check_duplicates(records, wb))
    duplicate_ids = {i.excel_row for i in issues if i.severity == ERROR and i.column == "No"}
    records = [r for r in records if r["_row"] not in duplicate_ids]
    return records, issues


def process_row(excel_row: int, cells: dict[str, str], picklists) -> tuple[dict, list[Issue]]:
    record: dict = {"_row": excel_row}
    issues: list[Issue] = []
    for col in COLUMNS:
        raw = cells.get(col.header, "")
        if raw and is_placeholder(raw):
            issues.append(Issue(excel_row, col.header, WARNING, f"placeholder '{raw}' → ignored"))
            raw = ""
        ctx = Context(column=col.header, picklists=picklists)
        value = PARSERS[col.kind](raw, ctx) if raw else _empty(col)
        record[col.key] = value
        record.update(ctx.extra)
        issues += [Issue(excel_row, col.header, WARNING, w) for w in ctx.warnings]
        if col.required and not value:
            issues.append(
                Issue(excel_row, col.header, ERROR, "required value missing → row skipped")
            )
    return record, issues


def _empty(col):
    if col.kind in ("text", "date"):
        return ""
    if col.kind == "id":
        return None
    return []


def check_duplicates(records: list[dict], wb: Workbook) -> list[Issue]:
    issues = []
    seen_ids: dict[int, int] = {}
    for r in records:
        if r["id"] in seen_ids:
            issues.append(Issue(r["_row"], "No", ERROR,
                                f"No {r['id']} already used in row {seen_ids[r['id']]} → row skipped"))  # fmt: skip
        else:
            seen_ids[r["id"]] = r["_row"]

    link_rows: dict[str, list[int]] = {}
    for r in records:
        for link in r["links"]:
            link_rows.setdefault(link.rstrip("/"), []).append(r["_row"])
    for link, rows in link_rows.items():
        for row in rows[1:]:
            issues.append(Issue(row, "Link", WARNING, f"same link as row {rows[0]}: {link}"))
    return issues


def render_report(issues: list[Issue], n_rows: int, n_records: int, details: bool = True) -> str:
    counts = Counter(i.severity for i in issues)
    lines = [
        "## OER catalogue validation",
        "",
        f"- Rows in sheet: **{n_rows}**",
        f"- Exported OER: **{n_records}**",
        f"- Errors (row skipped): **{counts[ERROR]}**",
        f"- Warnings (value ignored): **{counts[WARNING]}**",
    ]
    if issues and not details:
        lines += ["", "Run `uv run oercat validate` to list every problem."]
    elif issues:
        lines += ["", "| Row | Column | Severity | Problem |", "|---:|---|---|---|"]
        for i in sorted(issues, key=lambda i: (i.severity != ERROR, i.excel_row, i.column)):
            message = i.message.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {i.excel_row} | {i.column} | {i.severity} | {message} |")
    return "\n".join(lines) + "\n"
