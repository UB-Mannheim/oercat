"""Small, pure parsers that turn raw cell text into clean values.

Every parser has the signature ``parse(raw, ctx) -> value`` and reports
problems via ``ctx.warn(message)`` instead of raising, so one bad cell never
stops the build.
"""

import json
import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import yaml

from oercat.schema import MULTI_SEPARATOR

VOCAB_DIR = Path(__file__).parent / "vocab"

# W3C accessibility discovery vocabulary (accessibilityFeature), most common terms.
A11Y_TERMS = [
    "alternativeText", "audioDescription", "captions", "closedCaptions", "openCaptions",
    "transcript", "signLanguage", "longDescription", "describedMath", "highContrastDisplay",
    "largePrint", "braille", "tactileGraphic", "structuralNavigation", "tableOfContents",
    "readingOrder", "taggedPDF", "MathML", "synchronizedAudioText", "timingControl",
]  # fmt: skip

DISCIPLINE_RE = re.compile(r"hochschulfaechersystematik/(n\d+)/?$")
DATE_RE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")
AUTHOR_RE = re.compile(r"^(?P<name>.*?)\s*:\s*\{(?P<ident>[^}]*)\}\s*$")
COMMUNITY_RE = re.compile(r"^(?P<name>.*?)\s*\((?P<role>[SR])\)\s*$")
FILEFORMAT_RE = re.compile(r"^\.?([a-z0-9]{1,5})\b")
LICENSE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+-]*$")
LANGUAGE_RE = re.compile(r"^[a-z]{2,3}$")
PLACEHOLDER_RE = re.compile(r"^(\.+|LOOKUP.*|TODO|TBD|n/?a|null|none)$", re.IGNORECASE)


@dataclass
class Context:
    """Per-cell context handed to every parser."""

    column: str  # xlsx header, used to look up picklists and aliases
    picklists: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)  # side-channel output (e.g. ORCID links)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


@cache
def aliases() -> dict[str, dict[str, str]]:
    return yaml.safe_load((VOCAB_DIR / "aliases.yaml").read_text(encoding="utf-8")) or {}


@cache
def disciplines() -> dict[str, dict[str, str]]:
    path = VOCAB_DIR / "disciplines.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def fold(value: str) -> str:
    """Comparison key: lower case, letters and digits only ("Master’sStudent" == "Master'sStudent")."""
    return re.sub(r"[\W_]+", "", value.casefold())


def split_multi(raw: str) -> list[str]:
    """Split a ``a * b * c`` cell, strip values, drop empties and duplicates."""
    seen, out = set(), []
    for part in raw.split(MULTI_SEPARATOR):
        part = " ".join(part.split())
        if part and part not in seen:
            seen.add(part)
            out.append(part)
    return out


def apply_alias(value: str, column: str) -> str:
    table = aliases().get(column, {})
    return table.get(value, value)


# --- parsers -----------------------------------------------------------------


def parse_id(raw: str, ctx: Context) -> int | None:
    try:
        return int(float(raw))
    except ValueError:
        ctx.warn(f"'{raw}' is not a number")
        return None


def parse_text(raw: str, ctx: Context) -> str:
    return raw.strip()


def parse_tag(raw: str, ctx: Context) -> list[str]:
    return [apply_alias(v, ctx.column) for v in split_multi(raw)]


def parse_url(raw: str, ctx: Context) -> list[str]:
    urls = []
    for v in split_multi(raw):
        if v.startswith(("http://", "https://")):
            urls.append(v)
        else:
            ctx.warn(f"'{v}' is not a URL")
    return urls


def canon_picklist(value: str, allowed: list[str], column: str) -> str | None:
    value = apply_alias(value, column)
    by_fold = {fold(a): a for a in allowed}
    return by_fold.get(fold(value))


def parse_picklist(raw: str, ctx: Context) -> list[str]:
    allowed = ctx.picklists.get(ctx.column, [])
    out = []
    for v in split_multi(raw):
        canon = canon_picklist(v, allowed, ctx.column) if allowed else v
        if canon is None:
            ctx.warn(f"unknown value '{v}' (not in picklist) → dropped")
        elif canon not in out:
            out.append(canon)
    return out


def parse_keyword(raw: str, ctx: Context) -> list[str]:
    # Spelling variants ("Data literacy" / "Data Literacy") are merged across
    # all rows in export.unify_keywords.
    return [v.strip(" .;,") for v in split_multi(raw) if v.strip(" .;,")]


def parse_author(value: str) -> dict:
    """``Surname, Prename : {https://orcid.org/…}`` → ``{name, url, org}``."""
    def reorder_name(name: str) -> str:
        # "Surname, Prename" → "Prename Surname"; names without a comma
        # (e.g. organisations like "The Carpentries") are returned unchanged.
        surname, sep, prename = name.partition(",")
        if not sep or not prename.strip():
            return surname.strip()
        return f"{prename.strip()} {surname.strip()}"

    value = re.sub(r"\s*:\s*null\s*$", "", value)
    m = AUTHOR_RE.match(value)
    if not m:
        return {"name": reorder_name(value.strip()), "url": None, "org": False}
    ident = m["ident"].strip()
    org = ident.startswith("organization")
    url = ident.removeprefix("organization").strip() or None
    if url and not url.startswith("http"):
        url = None
    name = m["name"].strip() if org else reorder_name(m["name"].strip())
    return {"name": name, "url": url, "org": org}


def parse_authors(raw: str, ctx: Context) -> list[str]:
    names = []
    for v in split_multi(raw):
        author = parse_author(v)
        if author["name"] and author["name"] not in names:
            names.append(author["name"])
            if author["url"]:
                ctx.extra.setdefault("author_links", {})[author["name"]] = author["url"]
    return names


def parse_community(raw: str, ctx: Context) -> list[str]:
    names = []
    for v in split_multi(raw):
        m = COMMUNITY_RE.match(v)
        name, role = (m["name"], m["role"]) if m else (v, None)
        if name not in names:
            names.append(name)
        if role:
            ctx.extra.setdefault("community_roles", {})[name] = role
    return names


def parse_discipline(raw: str, ctx: Context) -> list[str]:
    codes = []
    for v in split_multi(raw):
        m = DISCIPLINE_RE.search(v)
        if not m:
            ctx.warn(f"'{v}' is not a Hochschulfächersystematik URI → dropped")
            continue
        code = m[1]
        if disciplines() and code not in disciplines():
            ctx.warn(f"unknown discipline code '{code}' → dropped")
        elif code not in codes:
            codes.append(code)
    return codes


def parse_language(raw: str, ctx: Context) -> list[str]:
    out = []
    for v in split_multi(raw):
        code = apply_alias(v, ctx.column).lower()
        if LANGUAGE_RE.match(code):
            out.append(code)
        else:
            ctx.warn(f"'{v}' is not an ISO 639 language code → dropped")
    return out


def parse_license(raw: str, ctx: Context) -> list[str]:
    out = []
    for v in split_multi(raw):
        v = apply_alias(v, ctx.column)
        if LICENSE_RE.match(v):
            out.append(v)
        else:
            ctx.warn(f"'{v}' is not a license identifier → dropped")
    return out


def parse_fileformat(raw: str, ctx: Context) -> list[str]:
    out = []
    for v in split_multi(raw):
        m = FILEFORMAT_RE.match(apply_alias(v, ctx.column).lower())
        if m:
            ext = "." + m[1]
            if ext not in out:
                out.append(ext)
        else:
            ctx.warn(f"'{v}' is not a file extension → dropped")
    return out


def parse_accessibility(raw: str, ctx: Context) -> list[str]:
    """Known vocabulary terms become filter values; anything else is kept as a note."""
    by_fold = {fold(t): t for t in A11Y_TERMS}
    terms, notes = [], []
    for v in split_multi(raw):
        key = apply_alias(v.rsplit("/", 1)[-1], ctx.column)
        term = by_fold.get(fold(key))
        if term:
            if term not in terms:
                terms.append(term)
        else:
            notes.append(v)
    if notes:
        ctx.extra["accessibility_note"] = " · ".join(notes)
    return terms


def parse_date(raw: str, ctx: Context) -> str:
    m = DATE_RE.match(raw.strip())
    if not m:
        ctx.warn(f"'{raw}' is not a date (YYYY, YYYY-MM or YYYY-MM-DD)")
        return ""
    ctx.extra["year"] = int(m[1])
    return raw.strip()


PARSERS = {
    "id": parse_id,
    "text": parse_text,
    "tag": parse_tag,
    "url": parse_url,
    "picklist": parse_picklist,
    "keyword": parse_keyword,
    "authors": parse_authors,
    "community": parse_community,
    "discipline": parse_discipline,
    "language": parse_language,
    "license": parse_license,
    "fileformat": parse_fileformat,
    "accessibility": parse_accessibility,
    "date": parse_date,
}


def is_placeholder(raw: str) -> bool:
    return bool(PLACEHOLDER_RE.match(raw.strip()))
