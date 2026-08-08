import logging
from collections.abc import Mapping
from typing import Any

SENSITIVE_HEADERS = {"authorization", "x-api-key", "api-key"}


def redact_headers(headers: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: "[REDACTED]" if key.lower() in SENSITIVE_HEADERS else value
        for key, value in headers.items()
    }


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
