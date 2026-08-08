import json
import re
import time
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.extraction.json_parser import parse_json_model
from app.models import Claim, PaperComparison, QuestionStatus, ResearchQuestion
from app.providers.llm.audit import record_ai_call
from app.providers.llm.base import LLMProvider, LLMResponse
from app.schemas.comparison import CandidateQuestionSet

PROMPT_VERSION = "candidate-question-v1"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "question_v1.txt"


class CandidateQuestionService:
    def __init__(self, session: Session, provider: LLMProvider, model: str) -> None:
        self.session = session
        self.provider = provider
        self.model = model

    async def generate(
        self,
        comparison: PaperComparison,
        claims: list[Claim],
        run_id: str | None = None,
    ) -> list[ResearchQuestion]:
        known_claim_ids = {claim.id for claim in claims}
        if not known_claim_ids:
            raise ValueError("Question generation requires Claim inputs")
        payload = {
            "comparison": self._comparison_payload(comparison),
            "claims": [
                {"claim_id": c.id, "paper_id": c.paper_id, "claim_text": c.claim_text}
                for c in claims
            ],
        }
        messages = [
            {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        schema = {
            "name": "candidate_question_set",
            "strict": True,
            "schema": CandidateQuestionSet.model_json_schema(),
        }
        started = time.perf_counter()
        response: LLMResponse | None = None
        try:
            response = await self.provider.complete(
                model=self.model, messages=messages, response_schema=schema
            )
            result = parse_json_model(response.content, CandidateQuestionSet)
            self._validate_claim_ids(result, known_claim_ids)
            comparison.research_gap = result.research_gap
            base_sequence = (
                self.session.scalar(select(func.count()).select_from(ResearchQuestion)) or 0
            )
            questions = [
                self._to_model(item, base_sequence + index)
                for index, item in enumerate(result.questions, 1)
            ]
            self.session.add_all(questions)
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
            return questions
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

    def _to_model(self, item, sequence: int) -> ResearchQuestion:
        family_code = re.sub(r"[^A-Z0-9]+", "-", item.family.upper()).strip("-")[:20]
        return ResearchQuestion(
            question_uid=f"RQ-{family_code}-{sequence:04d}",
            family=item.family,
            question=item.question,
            economic_mechanism=item.economic_mechanism,
            counter_mechanism=item.counter_mechanism,
            supporting_claims_json=item.supporting_claim_ids,
            contradicting_claims_json=item.contradicting_claim_ids,
            required_data_json=item.required_data,
            known_risks_json=item.known_risks,
            novelty_score=item.novelty_score,
            testability_score=item.testability_score,
            data_availability_score=item.data_availability_score,
            research_priority_score=item.research_priority_score,
            status=QuestionStatus.HUMAN_REVIEW_REQUIRED,
        )

    @staticmethod
    def _comparison_payload(comparison: PaperComparison) -> dict:
        return {
            field: getattr(comparison, f"{field}_json")
            for field in (
                "common_findings",
                "differences",
                "contradictions",
                "sample_differences",
                "universe_differences",
                "signal_differences",
                "cost_assumption_differences",
                "oos_differences",
                "survivorship_differences",
                "possible_explanations",
            )
        }

    @staticmethod
    def _validate_claim_ids(result: CandidateQuestionSet, known_claim_ids: set[int]) -> None:
        referenced = {
            claim_id
            for question in result.questions
            for claim_id in question.supporting_claim_ids + question.contradicting_claim_ids
        }
        invalid = referenced - known_claim_ids
        if invalid:
            raise ValueError(f"Questions reference unknown Claim IDs: {sorted(invalid)}")
