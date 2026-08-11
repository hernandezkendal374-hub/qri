from dataclasses import dataclass
from typing import Any

from app.providers.papers.http import HTTPPaperProvider


@dataclass(slots=True)
class OpenAccessLocation:
    url: str
    license: str | None
    version: str | None
    host_type: str | None


class UnpaywallProvider(HTTPPaperProvider):
    name = "unpaywall"
    endpoint = "https://api.unpaywall.org/v2"

    def __init__(self, email: str | None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.email = email

    async def lookup(self, doi: str) -> OpenAccessLocation | None:
        locations = await self.lookup_all(doi)
        return locations[0] if locations else None

    async def lookup_all(self, doi: str) -> list[OpenAccessLocation]:
        if not self.email:
            return []
        data = await self.request_json(f"{self.endpoint}/{doi}", params={"email": self.email})
        if not data.get("is_oa"):
            return []
        raw_locations = list(data.get("oa_locations") or [])
        best = data.get("best_oa_location")
        if best:
            raw_locations.insert(0, best)
        raw_locations.sort(key=lambda item: item.get("host_type") != "repository")
        results: list[OpenAccessLocation] = []
        seen: set[str] = set()
        for location in raw_locations:
            url = location.get("url_for_pdf")
            if not url or url in seen:
                continue
            seen.add(url)
            results.append(
                OpenAccessLocation(
                    url=url,
                    license=location.get("license"),
                    version=location.get("version"),
                    host_type=location.get("host_type"),
                )
            )
        return results
