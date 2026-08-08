from collections.abc import Iterable
from typing import Any

from app.providers.llm.base import LLMProvider, LLMResponse


class FixtureLLMProvider(LLMProvider):
    """Deterministic provider for tests only; never configured by production CLI."""

    def __init__(self, responses: Iterable[str]) -> None:
        self._responses = iter(responses)

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        content = next(self._responses)
        return LLMResponse(
            content=content,
            requested_model=model,
            returned_model="fixture-model",
            input_tokens=100,
            output_tokens=50,
            raw={"fixture": True},
        )
