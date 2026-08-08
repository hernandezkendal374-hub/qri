import re
import xml.etree.ElementTree as ET
from datetime import date

from app.providers.papers.base import PaperProvider, ProviderPaper
from app.providers.papers.http import HTTPPaperProvider

ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class ArxivProvider(HTTPPaperProvider, PaperProvider):
    name = "arxiv"
    endpoint = "https://export.arxiv.org/api/query"

    async def search(self, query: str, *, limit: int = 20) -> list[ProviderPaper]:
        response = await self.request(
            self.endpoint,
            params={
                "search_query": f'all:"{query}"',
                "start": 0,
                "max_results": min(limit, 100),
                "sortBy": "relevance",
            },
        )
        root = ET.fromstring(response.text)
        return [self._convert(entry) for entry in root.findall("a:entry", ATOM)]

    def _convert(self, entry: ET.Element) -> ProviderPaper:
        source_url = entry.findtext("a:id", namespaces=ATOM) or ""
        match = re.search(r"/abs/([^v]+)(?:v\d+)?$", source_url)
        arxiv_id = match.group(1) if match else source_url.rsplit("/", 1)[-1]
        published_text = entry.findtext("a:published", namespaces=ATOM)
        pdf_url = next(
            (
                link.get("href")
                for link in entry.findall("a:link", ATOM)
                if link.get("title") == "pdf"
            ),
            None,
        )
        return ProviderPaper(
            provider=self.name,
            provider_id=arxiv_id,
            arxiv_id=arxiv_id,
            title=" ".join((entry.findtext("a:title", namespaces=ATOM) or "").split()),
            abstract=" ".join((entry.findtext("a:summary", namespaces=ATOM) or "").split()),
            authors=[
                {"name": node.findtext("a:name", namespaces=ATOM)}
                for node in entry.findall("a:author", ATOM)
            ],
            publication_date=date.fromisoformat(published_text[:10]) if published_text else None,
            venue=entry.findtext("arxiv:journal_ref", namespaces=ATOM),
            doi=entry.findtext("arxiv:doi", namespaces=ATOM),
            source_url=source_url,
            pdf_url=pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
            open_access=True,
            license="arXiv",
            raw_metadata={"xml": ET.tostring(entry, encoding="unicode")},
        )
