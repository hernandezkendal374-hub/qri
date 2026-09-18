import hashlib
import time

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AICall
from app.providers.llm.base import LLMProvider, LLMResponse

_PER_MILLION = 1_000_000


def estimate_cost(input_tokens: int | None, output_tokens: int | None) -> float | None:
    """Price a call from the configured per-million-token rates.

    Returns None when no rate is configured or the gateway reported no usage,
    so an unpriced call is recorded as unknown rather than as free.
    """
    settings = get_settings()
    input_rate = settings.input_cost_per_million_tokens
    output_rate = settings.output_cost_per_million_tokens
    if not input_rate and not output_rate:
        return None
    if input_tokens is None and output_tokens is None:
        return None
    cost = (input_tokens or 0) * input_rate + (output_tokens or 0) * output_rate
    return round(cost / _PER_MILLION, 6)


def record_ai_call(
    session: Session,
    *,
    run_id: str | None,
    provider: LLMProvider,
    requested_model: str,
    prompt_version: str,
    response: LLMResponse | None,
    started: float,
    status: str,
) -> None:
    content = response.content if response else ""
    input_tokens = response.input_tokens if response else None
    output_tokens = response.output_tokens if response else None
    session.add(
        AICall(
            run_id=run_id,
            provider=type(provider).__name__,
            requested_model=requested_model,
            returned_model=response.returned_model if response else None,
            prompt_version=prompt_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=estimate_cost(input_tokens, output_tokens),
            latency_ms=int((time.perf_counter() - started) * 1000),
            response_hash=hashlib.sha256(content.encode()).hexdigest() if content else None,
            status=status,
        )
    )
