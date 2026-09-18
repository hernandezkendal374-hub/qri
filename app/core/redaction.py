"""Strip secrets out of text before it is stored or displayed.

The daily funnel captures each stage's stdout and stderr and persists the tail
of it to PipelineStageRun, where the dashboard renders it. A traceback can
easily carry a credential: httpx puts the full request URL in HTTPStatusError,
and the Stack Exchange API takes its key as a query parameter, so one failed
request is enough to write the key into the database and onto a web page.

Redacting at the point of storage covers every path into that field at once,
including tracebacks from code that has no idea a secret is involved.
"""

from __future__ import annotations

import re

from app.core.config import Settings, get_settings

REDACTED = "[REDACTED]"

# (pattern, replacement) pairs. These catch secret-shaped text even when the
# value never passed through this process, such as one printed by a subprocess.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # ?key=... / &api_key=... / &access_token=... in a URL query string
    (
        re.compile(
            r"(?i)([?&](?:key|api_?key|access_?token|token|secret|password|auth)=)"
            r"[^&\s\"'>]+"
        ),
        r"\1" + REDACTED,
    ),
    # scheme://user:password@host
    (
        re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@]+(@)"),
        r"\1" + REDACTED + r"\2",
    ),
    # Authorization: Bearer <token>
    (
        re.compile(r"(?i)(\bauthorization\b\s*[:=]\s*(?:bearer\s+)?)[^\s\"',)]+"),
        r"\1" + REDACTED,
    ),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), REDACTED),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"), REDACTED),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), REDACTED),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), REDACTED),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), REDACTED),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), REDACTED),
)

# Below this length a configured value is too generic to replace safely; a
# two-character key would rewrite half the text.
_MIN_SECRET_LENGTH = 6

_SECRET_SETTINGS = (
    "llm_api_key",
    "stackexchange_api_key",
    "semantic_scholar_api_key",
    "openalex_api_key",
)


def _configured_secrets(settings: Settings) -> list[str]:
    """The literal secret values this process holds, longest first."""
    values = []
    for name in _SECRET_SETTINGS:
        secret = getattr(settings, name, None)
        if secret is None:
            continue
        raw = secret.get_secret_value()
        if raw and len(raw) >= _MIN_SECRET_LENGTH:
            values.append(raw)
    # Longest first, so a secret that contains another is replaced as a whole.
    return sorted(values, key=len, reverse=True)


def redact_secrets(text: str | None, settings: Settings | None = None) -> str:
    """Replace configured and secret-shaped values in ``text`` with a marker."""
    if not text:
        return ""
    cleaned = text
    for value in _configured_secrets(settings or get_settings()):
        cleaned = cleaned.replace(value, REDACTED)
    for pattern, replacement in _PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned
