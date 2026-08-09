from datetime import date

import httpx
import pytest

from app.deduplication import deduplicate, normalize_doi, normalize_title
from app.discovery.service import DiscoveryService
from app.providers.papers.base import PaperProvider, ProviderPaper
from app.providers.papers.http import HTTPPaperProvider


def paper(**overrides) -> ProviderPaper:
    values = {"provider": "test", "provider_id": "1", "title": "Momentum & Returns!"}
    values.update(overrides)
    return ProviderPaper(**values)


def test_doi_normalization() -> None:
    assert normalize_doi(" https://doi.org/10.1234/ABC. ") == "10.1234/abc"
    assert normalize_doi("doi: 10.1/X") == "10.1/x"


def test_title_normalization() -> None:
    assert normalize_title("  Momentum: Returns — A Study ") == "momentum returns a study"


def test_deduplication_priority_and_fuzzy_title() -> None:
    first = paper(
        provider="arxiv",
        provider_id="a",
        arxiv_id="1234",
        authors=[{"name": "Jane Smith"}],
        publication_date=date(2020, 1, 1),
    )
    second = paper(
        provider="crossref",
        provider_id="b",
        title="Momentum and Returns",
        doi="10.1/x",
        abstract="Evidence",
        authors=[{"family": "Smith"}],
        publication_date=date(2021, 1, 1),
    )
    groups = deduplicate([first, second])
    assert len(groups) == 1
    assert len(groups[0].records) == 2
    assert groups[0].canonical.abstract == "Evidence"


@pytest.mark.asyncio
async def test_http_retry_after_server_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503 if attempts == 1 else 200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = HTTPPaperProvider(client=client, max_retries=2, retry_delay=0)
        assert await provider.request_json("https://example.test") == {"ok": True}
    assert attempts == 2


@pytest.mark.asyncio
async def test_http_timeout_is_raised_after_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = HTTPPaperProvider(client=client, max_retries=2, retry_delay=0)
        with pytest.raises(httpx.ReadTimeout):
            await provider.request_json("https://example.test")


class GoodProvider(PaperProvider):
    name = "good"

    async def search(self, query: str, *, limit: int = 20) -> list[ProviderPaper]:
        return [paper()]


class BadProvider(PaperProvider):
    name = "bad"

    async def search(self, query: str, *, limit: int = 20) -> list[ProviderPaper]:
        raise RuntimeError("offline")


@pytest.mark.asyncio
async def test_discovery_survives_one_provider_failure() -> None:
    result = await DiscoveryService([GoodProvider(), BadProvider()]).search("momentum")
    assert len(result.groups) == 1
    assert "bad" in result.errors
