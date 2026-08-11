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

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.api_key = api_key

    def _params(self, values: dict[str, Any]) -> dict[str, Any]:
        if self.api_key:
            return {**values, "api_key": self.api_key}
        return values

    async def search(self, query: str, *, limit: int = 20) -> list[ProviderPaper]:
        selection = (
            "id,doi,title,publication_date,authorships,primary_location,"
            "best_oa_location,locations,open_access,cited_by_count,abstract_inverted_index,ids"
        )
        data = await self.request_json(
            self.endpoint,
            params=self._params(
                {"search": query, "per-page": min(limit, 100), "select": selection}
            ),
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

    async def fulltext_locations(
        self, *, openalex_id: str | None = None, doi: str | None = None
    ) -> list[str]:
        selection = "id,best_oa_location,primary_location,locations,open_access"
        if openalex_id:
            data = await self.request_json(
                f"{self.endpoint}/{openalex_id}",
                params=self._params({"select": selection}),
            )
        elif doi:
            normalized_doi = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
            response = await self.request_json(
                self.endpoint,
                params=self._params(
                    {
                        "filter": f"doi:https://doi.org/{normalized_doi}",
                        "per-page": 1,
                        "select": selection,
                    }
                ),
            )
            results = response.get("results") or []
            if not results:
                return []
            data = results[0]
        else:
            return []
        locations = list(data.get("locations") or [])
        for key in ("best_oa_location", "primary_location"):
            if data.get(key):
                locations.insert(0, data[key])
        locations.sort(
            key=lambda item: (
                (item.get("source") or {}).get("type") != "repository",
                not bool(item.get("license")),
            )
        )
        urls: list[str] = []
        for location in locations:
            url = location.get("pdf_url")
            if location.get("is_oa") and url and url not in urls:
                urls.append(url)
        return urls
