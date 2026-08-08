from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class LLMResponse:
    content: str
    requested_model: str
    returned_model: str | None
    input_tokens: int | None
    output_tokens: int | None
    raw: dict[str, Any]


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """Return a provider-neutral completion."""
