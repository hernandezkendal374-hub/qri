from datetime import date
from typing import Any

from app.providers.papers.base import PaperProvider, ProviderPaper
from app.providers.papers.http import HTTPPaperProvider


class SemanticScholarProvider(HTTPPaperProvider, PaperProvider):
    name = "semantic_scholar"
    endpoint = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.api_key = api_key

    async def search(self, query: str, *, limit: int = 20) -> list[ProviderPaper]:
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        fields = (
            "paperId,title,abstract,authors,year,publicationDate,venue,"
            "externalIds,url,openAccessPdf,citationCount"
        )
        data = await self.request_json(
            self.endpoint,
            params={"query": query, "limit": min(limit, 100), "fields": fields},
            headers=headers,
        )
        return [self._convert(item) for item in data.get("data", []) if item.get("title")]

    def _convert(self, item: dict[str, Any]) -> ProviderPaper:
        external = item.get("externalIds") or {}
        open_pdf = item.get("openAccessPdf") or {}
        published = None
        if item.get("publicationDate"):
            try:
                published = date.fromisoformat(item["publicationDate"])
            except ValueError:
                pass
        return ProviderPaper(
            provider=self.name,
            provider_id=item["paperId"],
            semantic_scholar_id=item["paperId"],
            title=item["title"],
            abstract=item.get("abstract"),
            authors=[
                {"name": a.get("name"), "id": a.get("authorId")} for a in item.get("authors", [])
            ],
            publication_date=published,
            venue=item.get("venue") or None,
            doi=external.get("DOI"),
            arxiv_id=external.get("ArXiv"),
            source_url=item.get("url"),
            pdf_url=open_pdf.get("url"),
            open_access=bool(open_pdf.get("url")),
            citation_count=item.get("citationCount"),
            raw_metadata=item,
        )
