from dataclasses import dataclass

SHEET_DATA = "OER_Catalogue"
SHEET_PICKLISTS = "Picklists"
MULTI_SEPARATOR = "*"


@dataclass(frozen=True)
class Column:
    key: str  # field name in the exported JSON and in URLs (?type=Tutorial)
    header: str  # column header in the xlsx (compared after stripping whitespace)
    kind: str  # how the cell is parsed, see normalize.PARSERS
    multi: bool = False  # cell may hold several values separated by " * "
    required: bool = False  # row is skipped if empty
    boost: float = 0  # > 0: included in full-text search with this weight


COLUMNS: list[Column] = [
    Column("id", "No", "id", required=True),
    Column("title", "Title", "text", required=True, boost=4),
    Column("authors", "Authors", "authors", multi=True, boost=1.5),
    Column("description", "Description", "text", boost=1),
    Column("teaches", "Teaches", "text", boost=1),
    Column("links", "Link", "url", multi=True, required=True),
    Column("type", "LearningResourceType", "picklist", multi=True),
    Column("discipline", "Discipline", "discipline", multi=True),
    Column("language", "Language", "language", multi=True),
    Column("level", "ProficiencyLevel", "picklist", multi=True),
    Column("audience", "TargetGroup", "picklist", multi=True),
    Column("media", "MediaType", "picklist", multi=True),
    Column("keywords", "Keywords", "keyword", multi=True, boost=2),
    Column("license", "License", "license", multi=True),
    Column("community", "Community", "community", multi=True, boost=1),
    Column("publisher", "Publisher", "tag", boost=1),
    Column("format", "FileFormat", "fileformat", multi=True),
    Column("accessibility", "AccessibilityFeature", "accessibility", multi=True),
    Column("date", "PublicationDate", "date"),
]

# Filter groups in sidebar order. "year" is derived from PublicationDate.
FACETS: list[str] = [
    "type",
    "discipline",
    "language",
    "level",
    "audience",
    "media",
    "license",
    "community",
    "publisher",
    "format",
    "keywords",
    "authors",
    "accessibility",
]

# Facets whose values have a natural order (taken from the picklist) instead of
# being sorted by frequency.
ORDERED_FACETS: set[str] = {"level"}

COLUMNS_BY_KEY: dict[str, Column] = {c.key: c for c in COLUMNS}
