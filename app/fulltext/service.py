import hashlib
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fulltext.downloader import PDFDownloader
from app.models import Document, Paper
from app.models.entities import FullTextStatus
from app.parsing.base import DocumentParser
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
    ) -> None:
        self.session = session
        self.downloader = downloader
        self.parser = parser
        self.unpaywall = unpaywall
        self.storage_dir = storage_dir

    async def acquire(self, paper: Paper) -> FullTextResult:
        candidates = await self._candidate_urls(paper)
        errors: list[str] = []
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
        self.session.commit()
        return FullTextResult(
            paper.id,
            paper.fulltext_status,
            candidates[0] if candidates else None,
            reason=" | ".join(errors) if errors else "No legal open-access PDF location",
        )

    async def _candidate_urls(self, paper: Paper) -> list[str]:
        urls: list[str] = []
        if paper.arxiv_id:
            urls.append(f"https://arxiv.org/pdf/{paper.arxiv_id}")
        if paper.doi:
            try:
                location = await self.unpaywall.lookup(paper.doi)
                if location:
                    urls.append(location.url)
            except Exception:
                pass
        if paper.open_access and paper.pdf_url:
            urls.append(paper.pdf_url)
        return list(dict.fromkeys(urls))
