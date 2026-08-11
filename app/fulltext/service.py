import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fulltext.downloader import InvalidFullTextError, PDFDownloader
from app.models import Document, Paper
from app.models.entities import FullTextStatus
from app.parsing.base import DocumentParser
from app.providers.papers.openalex import OpenAlexProvider
from app.providers.papers.unpaywall import UnpaywallProvider


@dataclass(slots=True)
class FullTextResult:
    paper_id: int
    status: FullTextStatus
    source_url: str | None
    page_count: int = 0
    character_count: int = 0
    reason: str | None = None


class FullTextService:
    def __init__(
        self,
        session: Session,
        downloader: PDFDownloader,
        parser: DocumentParser,
        unpaywall: UnpaywallProvider,
        storage_dir: Path,
        openalex: OpenAlexProvider | None = None,
    ) -> None:
        self.session = session
        self.downloader = downloader
        self.parser = parser
        self.unpaywall = unpaywall
        self.storage_dir = storage_dir
        self.openalex = openalex

    async def acquire(self, paper: Paper) -> FullTextResult:
        paper.fulltext_attempted_at = datetime.now(UTC).replace(tzinfo=None)
        candidates, discovery_errors = await self._candidate_urls(paper)
        errors: list[str] = list(discovery_errors)
        for url in candidates:
            try:
                downloaded = await self.downloader.download(url)
                digest = hashlib.sha256(downloaded.content).hexdigest()
                existing = self.session.scalar(
                    select(Document).where(
                        Document.paper_id == paper.id,
                        Document.content_hash == digest,
                    )
                )
                if existing and existing.parsed_text:
                    paper.fulltext_status = FullTextStatus.FULLTEXT_AVAILABLE
                    paper.fulltext_failure_reason = None
                    self.session.commit()
                    return FullTextResult(
                        paper.id,
                        paper.fulltext_status,
                        downloaded.final_url,
                        character_count=len(existing.parsed_text),
                    )
                self.storage_dir.mkdir(parents=True, exist_ok=True)
                path = self.storage_dir / f"{paper.paper_uid}-{digest[:12]}.pdf"
                path.write_bytes(downloaded.content)
                parsed = self.parser.parse(path)
                self.session.add(
                    Document(
                        paper_id=paper.id,
                        document_type="PDF",
                        local_path=str(path.resolve()),
                        content_hash=digest,
                        parser_version=parsed.parser_version,
                        parsed_text=parsed.text,
                    )
                )
                paper.fulltext_status = FullTextStatus.FULLTEXT_AVAILABLE
                paper.fulltext_failure_reason = None
                paper.pdf_url = downloaded.final_url
                self.session.commit()
                return FullTextResult(
                    paper.id,
                    paper.fulltext_status,
                    downloaded.final_url,
                    len(parsed.pages),
                    len(parsed.text),
                )
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
        paper.fulltext_status = FullTextStatus.FULLTEXT_UNAVAILABLE
        reason = " | ".join(errors) if errors else "No legal open-access PDF location"
        paper.fulltext_failure_reason = reason
        self.session.commit()
        return FullTextResult(
            paper.id,
            paper.fulltext_status,
            candidates[0] if candidates else None,
            reason=reason,
        )

    def ingest_uploaded_pdf(self, paper: Paper, content: bytes) -> FullTextResult:
        if len(content) > self.downloader.max_bytes:
            raise InvalidFullTextError("PDF exceeds configured size limit")
        if not content.lstrip().startswith(b"%PDF-"):
            raise InvalidFullTextError("Uploaded file is not a PDF")
        digest = hashlib.sha256(content).hexdigest()
        existing = self.session.scalar(
            select(Document).where(
                Document.paper_id == paper.id,
                Document.content_hash == digest,
            )
        )
        paper.fulltext_attempted_at = datetime.now(UTC).replace(tzinfo=None)
        if existing and existing.parsed_text:
            paper.fulltext_status = FullTextStatus.FULLTEXT_AVAILABLE
            paper.fulltext_failure_reason = None
            self.session.commit()
            return FullTextResult(
                paper.id,
                paper.fulltext_status,
                "manual-upload",
                character_count=len(existing.parsed_text),
            )
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        path = self.storage_dir / f"{paper.paper_uid}-{digest[:12]}.pdf"
        path.write_bytes(content)
        try:
            parsed = self.parser.parse(path)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        self.session.add(
            Document(
                paper_id=paper.id,
                document_type="PDF",
                local_path=str(path.resolve()),
                content_hash=digest,
                parser_version=parsed.parser_version,
                parsed_text=parsed.text,
            )
        )
        paper.fulltext_status = FullTextStatus.FULLTEXT_AVAILABLE
        paper.fulltext_failure_reason = None
        self.session.commit()
        return FullTextResult(
            paper.id,
            paper.fulltext_status,
            "manual-upload",
            len(parsed.pages),
            len(parsed.text),
        )

    async def _candidate_urls(self, paper: Paper) -> tuple[list[str], list[str]]:
        urls: list[str] = []
        errors: list[str] = []
        if paper.arxiv_id:
            urls.append(f"https://arxiv.org/pdf/{paper.arxiv_id}")
        if paper.doi:
            try:
                locations = await self.unpaywall.lookup_all(paper.doi)
                urls.extend(location.url for location in locations)
            except Exception as exc:
                errors.append(f"Unpaywall lookup: {type(exc).__name__}: {exc}")
        if self.openalex and (paper.openalex_id or paper.doi):
            try:
                urls.extend(
                    await self.openalex.fulltext_locations(
                        openalex_id=paper.openalex_id, doi=paper.doi
                    )
                )
            except Exception as exc:
                errors.append(f"OpenAlex lookup: {type(exc).__name__}: {exc}")
        if paper.open_access and paper.pdf_url:
            urls.append(paper.pdf_url)
        return list(dict.fromkeys(urls)), errors
