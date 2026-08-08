import json
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.extraction.json_parser import parse_json_model
from app.models import Claim, Paper, PaperComparison
from app.providers.llm.audit import record_ai_call
from app.providers.llm.base import LLMProvider, LLMResponse
from app.schemas.comparison import MultiPaperComparison

PROMPT_VERSION = "multi-paper-comparison-v1"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "comparison_v1.txt"
SECTION_FIELDS = tuple(MultiPaperComparison.model_fields)


class MultiPaperComparisonService:
    def __init__(self, session: Session, provider: LLMProvider, model: str) -> None:
        self.session = session
        self.provider = provider
        self.model = model

    async def compare(
        self,
        papers: list[Paper],
        claims: list[Claim],
        run_id: str | None = None,
    ) -> PaperComparison:
        paper_ids = {paper.id for paper in papers}
        if len(paper_ids) != 3:
            raise ValueError("M5 comparison requires exactly three distinct papers")
        known_claim_ids = {claim.id for claim in claims if claim.paper_id in paper_ids}
        if not known_claim_ids:
            raise ValueError("Comparison requires persisted AUTHOR_CLAIM inputs")
        payload = {
            "papers": [{"paper_id": p.id, "title": p.title} for p in papers],
            "claims": [
                {
                    "claim_id": claim.id,
                    "paper_id": claim.paper_id,
                    "claim_text": claim.claim_text,
                    "direction": claim.direction,
                }
                for claim in claims
                if claim.id in known_claim_ids
            ],
        }
        messages = [
            {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        schema = {
            "name": "multi_paper_comparison",
            "strict": True,
            "schema": MultiPaperComparison.model_json_schema(),
        }
        started = time.perf_counter()
        response: LLMResponse | None = None
        try:
            response = await self.provider.complete(
                model=self.model, messages=messages, response_schema=schema
            )
            result = parse_json_model(response.content, MultiPaperComparison)
            self._validate_claim_ids(result, known_claim_ids)
            values = result.model_dump()
            comparison = PaperComparison(
                paper_ids_json=sorted(paper_ids),
                **{f"{field}_json": values[field] for field in SECTION_FIELDS},
                model=self.model,
                prompt_version=PROMPT_VERSION,
            )
            self.session.add(comparison)
            record_ai_call(
                self.session,
                run_id=run_id,
                provider=self.provider,
                requested_model=self.model,
                prompt_version=PROMPT_VERSION,
                response=response,
                started=started,
                status="SUCCESS",
            )
            self.session.commit()
            return comparison
        except Exception:
            self.session.rollback()
            record_ai_call(
                self.session,
                run_id=run_id,
                provider=self.provider,
                requested_model=self.model,
                prompt_version=PROMPT_VERSION,
                response=response,
                started=started,
                status="VALIDATION_ERROR" if response else "API_ERROR",
            )
            self.session.commit()
            raise

    @staticmethod
    def _validate_claim_ids(comparison: MultiPaperComparison, known_claim_ids: set[int]) -> None:
        referenced = {
            claim_id
            for field in SECTION_FIELDS
            for item in getattr(comparison, field)
            for claim_id in item.claim_ids
        }
        invalid = referenced - known_claim_ids
        if invalid:
            raise ValueError(f"Comparison references unknown Claim IDs: {sorted(invalid)}")
