import json
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.extraction.json_parser import parse_json_model
from app.models import ResearchQuestion, ResearchValidationSpec
from app.providers.llm.audit import record_ai_call
from app.providers.llm.base import LLMProvider, LLMResponse
from app.schemas.validation import ResearchValidationSpecification

PROMPT_VERSION = "research-validation-spec-v1"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "research_validation_v1.txt"


class ResearchValidationService:
    def __init__(self, session: Session, provider: LLMProvider, model: str) -> None:
        self.session = session
        self.provider = provider
        self.model = model

    async def generate(
        self,
        question: ResearchQuestion,
        evidence_package: dict,
        run_id: str | None = None,
    ) -> ResearchValidationSpec:
        messages = [
            {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
            {
                "role": "user",
                "content": json.dumps(
                    {"candidate_question": evidence_package}, ensure_ascii=False
                ),
            },
        ]
        response_schema = {
            "name": "research_validation_specification",
            "strict": True,
            "schema": ResearchValidationSpecification.model_json_schema(),
        }
        started = time.perf_counter()
        response: LLMResponse | None = None
        try:
            response = await self.provider.complete(
                model=self.model,
                messages=messages,
                response_schema=response_schema,
            )
            result = parse_json_model(response.content, ResearchValidationSpecification)
            question.plain_language_question = result.plain_language_question
            question.academic_question = result.academic_question
            question.question = result.academic_question
            row = self.session.scalar(
                select(ResearchValidationSpec).where(
                    ResearchValidationSpec.question_id == question.id
                )
            )
            if row:
                row.review_status = "DRAFT"
                row.specification_json = result.model_dump(mode="json")
                row.model = self.model
                row.prompt_version = PROMPT_VERSION
                row.approved_at = None
                row.exported_at = None
            else:
                row = ResearchValidationSpec(
                    question_id=question.id,
                    review_status="DRAFT",
                    specification_json=result.model_dump(mode="json"),
                    model=self.model,
                    prompt_version=PROMPT_VERSION,
                )
                self.session.add(row)
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
            return row
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
