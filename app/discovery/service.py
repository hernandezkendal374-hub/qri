import asyncio
from dataclasses import dataclass, field

from app.deduplication import deduplicate
from app.deduplication.service import PaperGroup
from app.providers.papers.base import PaperProvider, ProviderPaper


@dataclass
class DiscoveryResult:
    records: list[ProviderPaper]
    groups: list[PaperGroup]
    errors: dict[str, str] = field(default_factory=dict)


class DiscoveryService:
    def __init__(self, providers: list[PaperProvider]) -> None:
        self.providers = providers

    async def search(self, query: str, *, limit_per_provider: int = 20) -> DiscoveryResult:
        results = await asyncio.gather(
            *(provider.search(query, limit=limit_per_provider) for provider in self.providers),
            return_exceptions=True,
        )
        records: list[ProviderPaper] = []
        errors: dict[str, str] = {}
        for provider, result in zip(self.providers, results, strict=True):
            if isinstance(result, BaseException):
                errors[provider.name] = f"{type(result).__name__}: {result}"
            else:
                records.extend(result)
        return DiscoveryResult(records=records, groups=deduplicate(records), errors=errors)
