"""Write the clean records and the UI vocabulary as JSON for Hugo."""

import datetime as dt
import json
import re
from collections import Counter
from functools import cache
from pathlib import Path

import yaml

from oercat.normalize import VOCAB_DIR, disciplines, fold
from oercat.reader import Workbook
from oercat.schema import COLUMNS, COLUMNS_BY_KEY, FACETS, ORDERED_FACETS

LANGS = ("de", "en")
LARGE_FACET = 15  # facets with more values get a search box in the sidebar


def unify_keywords(records: list[dict]) -> None:
    """Merge spelling variants ("Data literacy" / "Data Literacy") to the most frequent one."""
    spellings: dict[str, Counter] = {}
    for r in records:
        for kw in r["keywords"]:
            spellings.setdefault(fold(kw), Counter())[kw] += 1
    canonical = {key: counter.most_common(1)[0][0] for key, counter in spellings.items()}
    for r in records:
        merged = []
        for kw in r["keywords"]:
            kw = canonical[fold(kw)]
            if kw not in merged:
                merged.append(kw)
        r["keywords"] = merged


def unify_disciplines(records: list[dict]) -> None:
    """Codes with the same label (study area n71 and subject n079 are both "Informatik")
    become one filter value: the most frequent code."""
    counts = Counter(code for r in records for code in r["discipline"])
    by_label: dict[str, str] = {}
    for code, _ in counts.most_common():
        by_label.setdefault(disciplines().get(code, {}).get("de", code), code)
    for r in records:
        merged = []
        for code in r["discipline"]:
            code = by_label[disciplines().get(code, {}).get("de", code)]
            if code not in merged:
                merged.append(code)
        r["discipline"] = merged


def clean_record(r: dict) -> dict:
    out = {c.key: r[c.key] for c in COLUMNS}
    out["year"] = r.get("year")
    out["author_links"] = r.get("author_links", {})
    out["community_roles"] = r.get("community_roles", {})
    out["accessibility_note"] = r.get("accessibility_note", "")
    return out


@cache
def label_overrides() -> dict:
    return yaml.safe_load((VOCAB_DIR / "labels.yaml").read_text(encoding="utf-8")) or {}


def humanize(value: str) -> str:
    """'AdvancedBeginner' → 'Advanced Beginner'."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)


def labels_for(facet: str, values: list[str], lang: str) -> dict[str, str]:
    if facet == "discipline":
        return {v: disciplines().get(v, {}).get(lang) or v for v in values}
    overrides = label_overrides().get(lang, {}).get(facet, {})
    if facet in ("type", "media", "level", "audience", "accessibility", "language"):
        return {v: overrides.get(v) or humanize(v) for v in values}
    return {v: overrides[v] for v in values if v in overrides}


def facet_values(facet: str, records: list[dict], picklists: dict) -> list[str]:
    counts = Counter(v for r in records for v in r[facet])
    if facet in ORDERED_FACETS:
        order = picklists.get(COLUMNS_BY_KEY[facet].header, [])
        return [v for v in order if v in counts] + [v for v in counts if v not in order]
    return [v for v, _ in counts.most_common()]


def build_vocab(records: list[dict], picklists: dict, source_mtime: dt.datetime) -> dict:
    facets, labels = [], {lang: {} for lang in LANGS}
    for key in FACETS:
        values = facet_values(key, records, picklists)
        facets.append(
            {"key": key, "ordered": key in ORDERED_FACETS, "large": len(values) > LARGE_FACET}
        )
        for lang in LANGS:
            labels[lang][key] = labels_for(key, values, lang)

    years = sorted({r["year"] for r in records if r["year"]})
    return {
        "facets": facets,
        "labels": labels,
        "search_fields": {c.key: c.boost for c in COLUMNS if c.boost},
        "years": years,
        "stats": {
            "total": len(records),
            "languages": len({v for r in records for v in r["language"]}),
            "disciplines": len({v for r in records for v in r["discipline"]}),
            "keywords": len({v for r in records for v in r["keywords"]}),
            "updated": source_mtime.date().isoformat(),
        },
    }


def export(records: list[dict], wb: Workbook, xlsx: Path, site_dir: Path) -> tuple[Path, Path]:
    unify_keywords(records)
    unify_disciplines(records)
    clean = sorted((clean_record(r) for r in records), key=lambda r: r["id"])
    updated = wb.modified or dt.datetime.fromtimestamp(xlsx.stat().st_mtime, tz=dt.UTC)
    vocab = build_vocab(clean, wb.picklists, updated)

    data_dir = site_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    oers_path, vocab_path = data_dir / "oers.json", data_dir / "vocab.json"
    oers_path.write_text(json.dumps(clean, ensure_ascii=False, indent=1), encoding="utf-8")
    vocab_path.write_text(json.dumps(vocab, ensure_ascii=False, indent=1), encoding="utf-8")
    return oers_path, vocab_path
