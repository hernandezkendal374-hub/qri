import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deduplication import normalize_doi, normalize_title
from app.deduplication.service import PaperGroup
from app.models import Document, Paper, PaperSource
from app.models.entities import FullTextStatus


class PaperRegistry:
    def __init__(self, session: Session) -> None:
        self.session = session

    def register(self, groups: list[PaperGroup]) -> list[Paper]:
        papers = [self._register_group(group) for group in groups]
        self.session.commit()
        return papers

    def _register_group(self, group: PaperGroup) -> Paper:
        record = group.canonical
        doi = normalize_doi(record.doi)
        paper = self._find_existing(record, doi)
        if paper is None:
            paper = Paper(
                doi=doi,
                arxiv_id=record.arxiv_id,
                semantic_scholar_id=record.semantic_scholar_id,
                openalex_id=record.openalex_id,
                title=record.title,
                normalized_title=normalize_title(record.title),
                abstract=record.abstract,
                authors_json=record.authors,
                publication_date=record.publication_date,
                venue=record.venue,
                source=record.provider,
                source_url=record.source_url,
                pdf_url=record.pdf_url,
                open_access=record.open_access,
                license=record.license,
                citation_count=record.citation_count,
                fulltext_status=FullTextStatus.ABSTRACT_ONLY
                if record.abstract
                else FullTextStatus.UNKNOWN,
                raw_hash=self._hash(record.raw_metadata),
            )
            self.session.add(paper)
            self.session.flush()
            if record.abstract:
                self.session.add(
                    Document(
                        paper_id=paper.id,
                        document_type="ABSTRACT",
                        content_hash=hashlib.sha256(record.abstract.encode()).hexdigest(),
                        parser_version="metadata-v1",
                        parsed_text=record.abstract,
                    )
                )
        existing = {(source.provider, source.provider_id) for source in paper.sources}
        for source in group.records:
            if (source.provider, source.provider_id) not in existing:
                paper.sources.append(
                    PaperSource(
                        provider=source.provider,
                        provider_id=source.provider_id,
                        raw_metadata_json=source.raw_metadata,
                    )
                )
        return paper

    def _find_existing(self, record: Any, doi: str | None) -> Paper | None:
        criteria = []
        if doi:
            criteria.append(Paper.doi == doi)
        for column, value in [
            (Paper.arxiv_id, record.arxiv_id),
            (Paper.semantic_scholar_id, record.semantic_scholar_id),
            (Paper.openalex_id, record.openalex_id),
        ]:
            if value:
                criteria.append(column == value)
        criteria.append(Paper.normalized_title == normalize_title(record.title))
        for criterion in criteria:
            paper = self.session.scalar(select(Paper).where(criterion).limit(1))
            if paper:
                return paper
        return None

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        payload = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
        return hashlib.sha256(payload).hexdigest()
