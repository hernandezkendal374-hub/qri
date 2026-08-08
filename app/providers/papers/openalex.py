from datetime import date
from typing import Any

from app.providers.papers.base import PaperProvider, ProviderPaper
from app.providers.papers.http import HTTPPaperProvider


def reconstruct_abstract(index: dict[str, list[int]] | None) -> str | None:
    if not index:
        return None
    positioned = [(position, word) for word, positions in index.items() for position in positions]
    return " ".join(word for _, word in sorted(positioned))


class OpenAlexProvider(HTTPPaperProvider, PaperProvider):
    name = "openalex"
    endpoint = "https://api.openalex.org/works"

    async def search(self, query: str, *, limit: int = 20) -> list[ProviderPaper]:
        selection = (
            "id,doi,title,publication_date,authorships,primary_location,"
            "open_access,cited_by_count,abstract_inverted_index,ids"
        )
        data = await self.request_json(
            self.endpoint,
            params={"search": query, "per-page": min(limit, 100), "select": selection},
        )
        return [self._convert(item) for item in data.get("results", []) if item.get("title")]

    def _convert(self, item: dict[str, Any]) -> ProviderPaper:
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        access = item.get("open_access") or {}
        raw_id = item.get("id", "")
        openalex_id = raw_id.rsplit("/", 1)[-1]
        published = (
            date.fromisoformat(item["publication_date"]) if item.get("publication_date") else None
        )
        return ProviderPaper(
            provider=self.name,
            provider_id=openalex_id,
            openalex_id=openalex_id,
            title=item["title"],
            abstract=reconstruct_abstract(item.get("abstract_inverted_index")),
            authors=[
                {
                    "name": a.get("author", {}).get("display_name"),
                    "id": a.get("author", {}).get("id"),
                }
                for a in item.get("authorships", [])
            ],
            publication_date=published,
            venue=source.get("display_name"),
            doi=item.get("doi"),
            source_url=location.get("landing_page_url") or raw_id,
            pdf_url=location.get("pdf_url"),
            open_access=access.get("is_oa"),
            license=location.get("license"),
            citation_count=item.get("cited_by_count"),
            raw_metadata=item,
        )
