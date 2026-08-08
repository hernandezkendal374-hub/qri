import asyncio
from typing import Any

import httpx


class HTTPPaperProvider:
    name = "base"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 20.0,
        max_retries: int = 3,
        retry_delay: float = 0.25,
    ) -> None:
        self._client = client
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    async def request(self, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                if self._client is not None:
                    response = await self._client.get(url, timeout=self.timeout, **kwargs)
                else:
                    async with httpx.AsyncClient(
                        timeout=self.timeout,
                        headers={"User-Agent": "QRI/0.1 (academic research POC)"},
                        follow_redirects=True,
                    ) as client:
                        response = await client.get(url, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response
            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt + 1 < self.max_retries:
                    await asyncio.sleep(self.retry_delay * (2**attempt))
        assert last_error is not None
        raise last_error

    async def request_json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        return (await self.request(url, **kwargs)).json()
