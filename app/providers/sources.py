from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CommunityAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer_id: int | str
    body: str = ""
    score: int = 0
    is_accepted: bool = False
    author_name: str | None = None
    author_reputation: int | None = None
    edited_at: int | None = None
    links: list[str] = Field(default_factory=list)


class CommunityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    provider_id: str
    title: str
    body: str = ""
    tags: list[str] = Field(default_factory=list)
    score: int = 0
    view_count: int = 0
    author_name: str | None = None
    author_reputation: int | None = None
    accepted_answer: CommunityAnswer | None = None
    answers: list[CommunityAnswer] = Field(default_factory=list)
    creation_date: int | None = None
    last_activity_date: int | None = None
    last_edit_date: int | None = None
    source_url: str
    links: list[str] = Field(default_factory=list)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchSourceProvider(ABC):
    """Provider boundary for non-paper research sources.

    Community records are deliberately not Paper/Claim/Evidence records.
    """

    name: str
    tier: str = "COMMUNITY"

    @abstractmethod
    async def search(self, query: str, *, limit: int = 20) -> list[CommunityRecord]:
        """Search a source and return untrusted, provider-neutral records."""
