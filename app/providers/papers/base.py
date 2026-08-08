from abc import ABC, abstractmethod
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProviderPaper(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    provider_id: str
    title: str
    abstract: str | None = None
    authors: list[dict[str, Any]] = Field(default_factory=list)
    publication_date: date | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    semantic_scholar_id: str | None = None
    openalex_id: str | None = None
    source_url: str | None = None
    pdf_url: str | None = None
    open_access: bool | None = None
    license: str | None = None
    citation_count: int | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class PaperProvider(ABC):
    name: str

    @abstractmethod
    async def search(self, query: str, *, limit: int = 20) -> list[ProviderPaper]:
        """Search papers and return provider-neutral records."""
