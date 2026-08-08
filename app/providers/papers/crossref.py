from datetime import date
from typing import Any

from app.providers.papers.base import PaperProvider, ProviderPaper
from app.providers.papers.http import HTTPPaperProvider


class CrossrefProvider(HTTPPaperProvider, PaperProvider):
    name = "crossref"
    endpoint = "https://api.crossref.org/works"

    async def search(self, query: str, *, limit: int = 20) -> list[ProviderPaper]:
        data = await self.request_json(
            self.endpoint, params={"query.bibliographic": query, "rows": min(limit, 100)}
        )
        return [
            self._convert(item)
            for item in data.get("message", {}).get("items", [])
            if item.get("title")
        ]

    def _convert(self, item: dict[str, Any]) -> ProviderPaper:
        parts = (item.get("published-print") or item.get("published-online") or {}).get(
            "date-parts", []
        )
        values = parts[0] if parts else []
        published = (
            date(
                values[0], values[1] if len(values) > 1 else 1, values[2] if len(values) > 2 else 1
            )
            if values
            else None
        )
        links = item.get("link") or []
        pdf_url = next(
            (link.get("URL") for link in links if "pdf" in link.get("content-type", "")), None
        )
        return ProviderPaper(
            provider=self.name,
            provider_id=item.get("DOI") or item.get("URL"),
            title=item["title"][0],
            abstract=item.get("abstract"),
            authors=[
                {"given": a.get("given"), "family": a.get("family"), "orcid": a.get("ORCID")}
                for a in item.get("author", [])
            ],
            publication_date=published,
            venue=(item.get("container-title") or [None])[0],
            doi=item.get("DOI"),
            source_url=item.get("URL"),
            pdf_url=pdf_url,
            open_access=True if pdf_url else None,
            license=(item.get("license") or [{}])[0].get("URL"),
            citation_count=item.get("is-referenced-by-count"),
            raw_metadata=item,
        )
