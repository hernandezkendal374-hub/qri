import json
import re

from pydantic import BaseModel


def parse_json_object(content: str) -> dict:
    """Parse one JSON object, tolerating only surrounding text/code fences."""
    cleaned = content.strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    decoder = json.JSONDecoder()
    starts = [index for index, character in enumerate(cleaned) if character == "{"]
    last_error: Exception | None = None
    for start in starts:
        try:
            value, _ = decoder.raw_decode(cleaned[start:])
            if not isinstance(value, dict):
                raise ValueError("Top-level JSON value must be an object")
            return value
        except json.JSONDecodeError as exc:
            last_error = exc
    if last_error:
        raise ValueError(f"No valid JSON object: {last_error}") from last_error
    raise ValueError("No JSON object found")


def parse_json_model[SchemaT: BaseModel](content: str, schema: type[SchemaT]) -> SchemaT:
    return schema.model_validate(parse_json_object(content))
