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
        if not self.email:
            return None
        data = await self.request_json(f"{self.endpoint}/{doi}", params={"email": self.email})
        if not data.get("is_oa"):
            return None
        location = data.get("best_oa_location") or {}
        url = location.get("url_for_pdf")
        if not url:
            return None
        return OpenAccessLocation(
            url=url,
            license=location.get("license"),
            version=location.get("version"),
            host_type=location.get("host_type"),
        )
