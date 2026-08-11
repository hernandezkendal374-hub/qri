from pathlib import Path

import httpx
import pymupdf
import pytest
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.session import build_engine
from app.fulltext.downloader import InvalidFullTextError, PDFDownloader
from app.fulltext.service import FullTextService
from app.models import Paper
from app.models.entities import FullTextStatus
from app.parsing.pymupdf_parser import PyMuPDFParser
from app.providers.papers.unpaywall import UnpaywallProvider


def make_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "Momentum evidence on page one")
    content = document.tobytes()
    document.close()
    return content


@pytest.mark.asyncio
async def test_downloader_rejects_html_disguised_as_pdf() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="<html>paywall</html>", request=request)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(InvalidFullTextError, match="not a PDF"):
            await PDFDownloader(client=client).download("https://example.test/paper.pdf")


def test_parser_preserves_page_offsets(tmp_path: Path) -> None:
    path = tmp_path / "paper.pdf"
    path.write_bytes(make_pdf())
    parsed = PyMuPDFParser().parse(path)
    assert len(parsed.pages) == 1
    assert parsed.pages[0].page_number == 1
    assert (
        parsed.text[parsed.pages[0].start_offset : parsed.pages[0].end_offset]
        == parsed.pages[0].text
    )


@pytest.mark.asyncio
async def test_no_location_is_unavailable_without_losing_abstract(tmp_path: Path) -> None:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        paper = Paper(
            title="Metadata only",
            normalized_title="metadata only",
            abstract="Available abstract",
            authors_json=[],
            source="test",
        )
        session.add(paper)
        session.commit()
        service = FullTextService(
            session,
            PDFDownloader(),
            PyMuPDFParser(),
            UnpaywallProvider(None),
            tmp_path,
        )
        result = await service.acquire(paper)
        assert result.status == FullTextStatus.FULLTEXT_UNAVAILABLE
        assert result.reason == "No legal open-access PDF location"


@pytest.mark.asyncio
async def test_no_location_without_abstract_is_unavailable(tmp_path: Path) -> None:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        paper = Paper(
            title="No content",
            normalized_title="no content",
            authors_json=[],
            source="test",
        )
        session.add(paper)
        session.commit()
        service = FullTextService(
            session,
            PDFDownloader(),
            PyMuPDFParser(),
            UnpaywallProvider(None),
            tmp_path,
        )
        result = await service.acquire(paper)
        assert result.status == FullTextStatus.FULLTEXT_UNAVAILABLE


@pytest.mark.asyncio
async def test_unpaywall_returns_all_pdf_locations_with_repository_first() -> None:
    payload = {
        "is_oa": True,
        "best_oa_location": {
            "url_for_pdf": "https://publisher.test/paper.pdf",
            "host_type": "publisher",
        },
        "oa_locations": [
            {
                "url_for_pdf": "https://publisher.test/paper.pdf",
                "host_type": "publisher",
            },
            {
                "url_for_pdf": "https://repository.test/paper.pdf",
                "host_type": "repository",
            },
        ],
    }
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json=payload, request=request)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        locations = await UnpaywallProvider("researcher@example.com", client=client).lookup_all(
            "10.1234/example"
        )
    assert [location.url for location in locations] == [
        "https://repository.test/paper.pdf",
        "https://publisher.test/paper.pdf",
    ]


def test_manual_pdf_upload_is_parsed_and_persisted(tmp_path: Path) -> None:
    engine = build_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        paper = Paper(
            title="Manual upload",
            normalized_title="manual upload",
            authors_json=[],
            source="test",
        )
        session.add(paper)
        session.commit()
        service = FullTextService(
            session,
            PDFDownloader(),
            PyMuPDFParser(),
            UnpaywallProvider(None),
            tmp_path,
        )
        result = service.ingest_uploaded_pdf(paper, make_pdf())
        assert result.status == FullTextStatus.FULLTEXT_AVAILABLE
        assert result.page_count == 1
        assert result.character_count > 0
        assert paper.fulltext_failure_reason is None
