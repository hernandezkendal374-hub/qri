import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.providers.papers.base import ProviderPaper


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    normalized = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", normalized)
    normalized = re.sub(r"^doi:\s*", "", normalized)
    return normalized.rstrip(" .") or None


def normalize_title(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).casefold()
    value = value.replace("&", " and ")
    value = re.sub(r"[^\w\s]", " ", value)
    return " ".join(value.split())


@dataclass
class PaperGroup:
    canonical: ProviderPaper
    records: list[ProviderPaper] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.records:
            self.records.append(self.canonical)


def _exact_identifier_match(a: ProviderPaper, b: ProviderPaper) -> bool:
    pairs = [
        (normalize_doi(a.doi), normalize_doi(b.doi)),
        (a.arxiv_id, b.arxiv_id),
        (a.semantic_scholar_id, b.semantic_scholar_id),
        (a.openalex_id, b.openalex_id),
    ]
    return any(left and right and left.casefold() == right.casefold() for left, right in pairs)


def _same_work(a: ProviderPaper, b: ProviderPaper) -> bool:
    if _exact_identifier_match(a, b):
        return True
    left, right = normalize_title(a.title), normalize_title(b.title)
    if left == right:
        return True
    left_author = _first_author(a)
    right_author = _first_author(b)
    if not a.publication_date or not b.publication_date or not left_author or not right_author:
        return False
    years_match = abs(a.publication_date.year - b.publication_date.year) <= 1
    authors_match = left_author == right_author
    return years_match and authors_match and SequenceMatcher(None, left, right).ratio() >= 0.90


def _first_author(record: ProviderPaper) -> str | None:
    if not record.authors:
        return None
    author = record.authors[0]
    value = author.get("family") or author.get("name")
    return normalize_title(str(value)).split()[-1] if value else None


def _quality(record: ProviderPaper) -> tuple[int, int, int]:
    return (bool(record.abstract), bool(record.doi), record.citation_count or 0)


def deduplicate(records: list[ProviderPaper]) -> list[PaperGroup]:
    groups: list[PaperGroup] = []
    for record in records:
        group = next(
            (candidate for candidate in groups if _same_work(record, candidate.canonical)), None
        )
        if group is None:
            groups.append(PaperGroup(record))
        else:
            group.records.append(record)
            if _quality(record) > _quality(group.canonical):
                group.canonical = record
    return groups
