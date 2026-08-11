import json
from typing import Any

import httpx

from app.providers.llm.base import LLMProvider, LLMResponse


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        response_schema: dict[str, Any] | None = None,
    ) -> LLMResponse:
        request_messages = [message.copy() for message in messages]
        payload: dict[str, Any] = {"model": model, "messages": request_messages}
        if response_schema:
            # Use the broadly supported JSON-object mode and perform strict Pydantic
            # validation locally. Some compatible gateways corrupt nested $ref schemas
            # when proxying json_schema to different upstream model vendors.
            payload["response_format"] = {"type": "json_object"}
            schema_instruction = (
                "\n\nMANDATORY OUTPUT CONTRACT:\n"
                "Return exactly one JSON object and no surrounding prose or markdown. "
                "The object must validate against this JSON Schema. Do not add fields.\n"
                + json.dumps(response_schema["schema"], ensure_ascii=False, separators=(",", ":"))
            )
            if request_messages and request_messages[0].get("role") == "system":
                request_messages[0]["content"] += schema_instruction
            else:
                request_messages.insert(0, {"role": "system", "content": schema_instruction})
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        usage = data.get("usage", {})
        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            requested_model=model,
            returned_model=data.get("model"),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            raw=data,
        )
