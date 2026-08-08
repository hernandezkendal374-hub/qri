from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


class InvalidFullTextError(ValueError):
    pass


@dataclass(slots=True)
class DownloadedPDF:
    content: bytes
    final_url: str
    content_type: str | None


class PDFDownloader:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 45.0,
        max_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        self.client = client
        self.timeout = timeout
        self.max_bytes = max_bytes

    async def download(self, url: str) -> DownloadedPDF:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise InvalidFullTextError("Only absolute HTTP(S) URLs are accepted")
        headers = {
            "Accept": "application/pdf,application/octet-stream;q=0.9",
            "User-Agent": "QRI/0.1 (academic research POC)",
        }
        if self.client:
            response = await self.client.get(
                url, timeout=self.timeout, headers=headers, follow_redirects=True
            )
        else:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)
        response.raise_for_status()
        length = response.headers.get("content-length")
        if length and int(length) > self.max_bytes:
            raise InvalidFullTextError("PDF exceeds configured size limit")
        content = response.content
        if len(content) > self.max_bytes:
            raise InvalidFullTextError("PDF exceeds configured size limit")
        if not content.lstrip().startswith(b"%PDF-"):
            raise InvalidFullTextError("Response is not a PDF")
        return DownloadedPDF(
            content=content,
            final_url=str(response.url),
            content_type=response.headers.get("content-type"),
        )
