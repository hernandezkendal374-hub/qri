from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from app.providers.papers.http import HTTPPaperProvider
from app.providers.sources import CommunityAnswer, CommunityRecord, ResearchSourceProvider

BASE_URL = "https://api.stackexchange.com/2.3"
PROMPT_INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all instructions",
    "system prompt",
    "developer message",
    "run this code",
    "change model behavior",
    "jailbreak",
)
LINK_PATTERN = re.compile(r"https?://[^\s)<>]+", re.IGNORECASE)


def sanitize_external_text(value: str | None, *, max_chars: int = 12_000) -> str:
    """Keep community text as inert evidence-like input, never instructions."""
    if not value:
        return ""
    safe_lines = []
    for line in value.splitlines():
        lowered = line.casefold()
        for marker in PROMPT_INJECTION_MARKERS:
            if marker in lowered:
                line = re.sub(
                    re.escape(marker),
                    "[外部文本中的指令性内容已忽略]",
                    line,
                    flags=re.IGNORECASE,
                )
        safe_lines.append(line)
    return "\n".join(safe_lines)[:max_chars]


class QuantStackExchangeProvider(HTTPPaperProvider, ResearchSourceProvider):
    """Official Stack Exchange API adapter for Quantitative Finance SE."""

    name = "quant_stackexchange"
    tier = "COMMUNITY"

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.api_key = api_key

    async def search(self, query: str, *, limit: int = 20) -> list[CommunityRecord]:
        params: dict[str, Any] = {
            "site": "quant",
            "q": sanitize_external_text(query, max_chars=240),
            "pagesize": min(max(1, limit), 100),
            "filter": "withbody",
            "order": "desc",
            "sort": "relevance",
        }
        if self.api_key:
            params["key"] = self.api_key
        payload = await self.request_json(f"{BASE_URL}/search/advanced", params=params)
        items = payload.get("items") or []
        records: list[CommunityRecord] = []
        for item in items:
            question_id = item.get("question_id")
            if question_id is None or not item.get("title"):
                continue
            answers = await self._answers(question_id, params)
            accepted = next((answer for answer in answers if answer.is_accepted), None)
            records.append(
                CommunityRecord(
                    provider=self.name,
                    provider_id=str(question_id),
                    title=sanitize_external_text(item.get("title"), max_chars=500),
                    body=sanitize_external_text(item.get("body")),
                    tags=[str(tag) for tag in item.get("tags", [])],
                    score=int(item.get("score") or 0),
                    view_count=int(item.get("view_count") or 0),
                    author_name=(item.get("owner") or {}).get("display_name"),
                    author_reputation=(item.get("owner") or {}).get("reputation"),
                    accepted_answer=accepted,
                    answers=answers,
                    creation_date=item.get("creation_date"),
                    last_activity_date=item.get("last_activity_date"),
                    last_edit_date=item.get("last_edit_date"),
                    source_url=item.get("link") or f"https://quant.stackexchange.com/questions/{question_id}",
                    links=self._links(item.get("body")),
                    raw_metadata={"question": item, "answer_count": len(answers)},
                )
            )
        return records

    async def _answers(
        self, question_id: int, base_params: dict[str, Any]
    ) -> list[CommunityAnswer]:
        params = {
            "site": "quant",
            "filter": "withbody",
            "pagesize": 20,
            "sort": "votes",
            "order": "desc",
        }
        if self.api_key:
            params["key"] = self.api_key
        try:
            payload = await self.request_json(
                f"{BASE_URL}/questions/{question_id}/answers", params=params
            )
        except Exception:
            # Search results remain useful if a per-question answer request is
            # rate limited.  This is a shadow source, never a hard dependency.
            return []
        result: list[CommunityAnswer] = []
        for item in payload.get("items") or []:
            result.append(
                CommunityAnswer(
                    answer_id=item.get("answer_id", ""),
                    body=sanitize_external_text(item.get("body")),
                    score=int(item.get("score") or 0),
                    is_accepted=bool(item.get("is_accepted")),
                    author_name=(item.get("owner") or {}).get("display_name"),
                    author_reputation=(item.get("owner") or {}).get("reputation"),
                    edited_at=item.get("last_edit_date"),
                    links=self._links(item.get("body")),
                )
            )
        return result

    @staticmethod
    def _links(text: str | None) -> list[str]:
        return sorted(set(LINK_PATTERN.findall(text or "")))[:20]


def unix_datetime(value: int | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.utcfromtimestamp(value)
    except (OverflowError, OSError, ValueError):
        return None


def absolute_link(value: str) -> str:
    return urljoin("https://quant.stackexchange.com/", value)
