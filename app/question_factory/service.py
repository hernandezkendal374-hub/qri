import json
import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.extraction.json_parser import parse_json_model, parse_json_object
from app.models import Claim, InvestmentRelevance, PaperComparison, QuestionStatus, ResearchQuestion
from app.providers.llm.audit import record_ai_call
from app.providers.llm.base import LLMProvider, LLMResponse
from app.schemas.comparison import CandidateQuestionSet

PROMPT_VERSION = "candidate-question-v2"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "question_v1.txt"
EXCLUDED_QUESTION_MARKERS = (
    "日本市场",
    "日本股市",
    "中国市场",
    "中国股市",
    "欧洲市场",
    "japanese market",
    "china market",
    "european market",
    "期权隐含",
    "期权数据",
    "option-implied",
    "options data",
)
MIN_RESEARCH_PRIORITY = 0.72
MIN_TESTABILITY = 0.65


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
            result = self._parse_result(response.content)
            self._validate_claim_ids(result, known_claim_ids)
            comparison.research_gap = result.research_gap
            existing_questions = list(
                self.session.scalars(select(ResearchQuestion.question))
            )
            accepted_items = []
            normalized_questions = [
                self._normalize_question(question) for question in existing_questions
            ]
            for item in result.questions:
                if not self._in_current_scope(item.academic_question):
                    continue
                if (
                    item.research_priority_score < MIN_RESEARCH_PRIORITY
                    or item.testability_score < MIN_TESTABILITY
                ):
                    continue
                normalized = self._normalize_question(item.academic_question)
                if any(
                    SequenceMatcher(None, normalized, existing).ratio() >= 0.90
                    for existing in normalized_questions
                    if existing
                ):
                    continue
                accepted_items.append(item)
                normalized_questions.append(normalized)
            base_sequence = (
                self.session.scalar(select(func.count()).select_from(ResearchQuestion)) or 0
            )
            questions = [
                self._to_model(item, base_sequence + index)
                for index, item in enumerate(accepted_items, 1)
            ]
            self.session.add_all(questions)
            self.session.flush()
            for question in questions:
                self.session.add(
                    InvestmentRelevance(
                        question_id=question.id,
                        hypothesis_convertibility=(
                            0.85
                            if question.priority_type == "P0_ALPHA_CANDIDATE"
                            else 0.65
                            if question.priority_type == "P1_POTENTIAL_ALPHA"
                            else 0.40
                        ),
                        data_availability=question.data_availability_score or 0.0,
                        holding_period_fit=0.5,
                        implementation_complexity=0.5,
                        forward_validation_feasibility=question.testability_score or 0.0,
                        capital_fit=0.5,
                        summary=(
                            "这是研究转化性分层，不预测收益、风险调整收益或利润。"
                        ),
                    )
                )
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
        if not family_code:
            family_code = "RESEARCH"
        return ResearchQuestion(
            question_uid=f"RQ-{family_code}-{sequence:04d}",
            family=self._sanitize_text(item.family),
            question=self._sanitize_text(item.academic_question),
            plain_language_question=self._sanitize_text(item.plain_language_question),
            academic_question=self._sanitize_text(item.academic_question),
            economic_mechanism=self._sanitize_text(item.economic_mechanism),
            counter_mechanism=self._sanitize_text(item.counter_mechanism),
            supporting_claims_json=item.supporting_claim_ids,
            contradicting_claims_json=item.contradicting_claim_ids,
            required_data_json=[self._sanitize_text(value) for value in item.required_data],
            known_risks_json=[self._sanitize_text(value) for value in item.known_risks],
            novelty_score=item.novelty_score,
            testability_score=item.testability_score,
            data_availability_score=item.data_availability_score,
            research_priority_score=item.research_priority_score,
            priority_type=self._priority_type(item.research_priority_score),
            status=QuestionStatus.HUMAN_REVIEW_REQUIRED,
        )

    @staticmethod
    def _priority_type(score: float) -> str:
        if score >= 0.85:
            return "P0_ALPHA_CANDIDATE"
        if score >= 0.75:
            return "P1_POTENTIAL_ALPHA"
        if score >= 0.60:
            return "P2_RESEARCH_INFRASTRUCTURE"
        return "P3_EXPLORATORY"

    @staticmethod
    def _parse_result(content: str) -> CandidateQuestionSet:
        try:
            return parse_json_model(content, CandidateQuestionSet)
        except Exception as original_error:
            value = parse_json_object(content)
            questions = value.get("questions")
            score_fields = (
                "novelty_score",
                "testability_score",
                "data_availability_score",
                "research_priority_score",
            )
            if not isinstance(questions, list) or not all(
                field in value for field in score_fields
            ):
                raise original_error
            for question in questions:
                if not isinstance(question, dict):
                    raise original_error
                for field in score_fields:
                    question.setdefault(field, value[field])
            for field in score_fields:
                value.pop(field, None)
            return CandidateQuestionSet.model_validate(value)

    @staticmethod
    def _normalize_question(value: str) -> str:
        value = unicodedata.normalize("NFKC", value).casefold()
        return "".join(character for character in value if character.isalnum())

    @staticmethod
    def _in_current_scope(value: str) -> bool:
        normalized = unicodedata.normalize("NFKC", value).casefold()
        return not any(marker in normalized for marker in EXCLUDED_QUESTION_MARKERS)

    @staticmethod
    def _sanitize_text(value: str) -> str:
        return re.sub(r"\bPaper\s+\d+\b", "证据来源", value, flags=re.IGNORECASE)

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
