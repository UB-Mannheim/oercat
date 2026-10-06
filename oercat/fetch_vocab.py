"""Refresh vocab/disciplines.json from the Hochschulfächersystematik SKOS file."""

import json
import re
import urllib.request

from oercat.normalize import VOCAB_DIR

SOURCE_URL = (
    "https://raw.githubusercontent.com/dini-ag-kim/hochschulfaechersystematik/"
    "master/hochschulfaechersystematik.ttl"
)
CONCEPT_RE = re.compile(r"^<(n\d+)> a skos:Concept ;(.*?)(?=^<|\Z)", re.MULTILINE | re.DOTALL)
LABEL_RE = re.compile(r'"([^"]+)"@(de|en)\b')


def parse_ttl(ttl: str) -> dict[str, dict[str, str]]:
    """Extract ``code -> {de, en}`` prefLabels from the Turtle file."""
    out = {}
    for code, body in CONCEPT_RE.findall(ttl):
        pref = body.split("skos:prefLabel", 1)[-1].split(" ;", 1)[0]
        labels = {lang: text for text, lang in LABEL_RE.findall(pref)}
        if labels:
            out[code] = labels
    return out


def fetch() -> int:
    with urllib.request.urlopen(SOURCE_URL, timeout=30) as resp:
        ttl = resp.read().decode("utf-8")
    labels = parse_ttl(ttl)
    path = VOCAB_DIR / "disciplines.json"
    path.write_text(json.dumps(dict(sorted(labels.items())), ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")  # fmt: skip
    return len(labels)
