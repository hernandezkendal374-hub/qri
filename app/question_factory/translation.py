import json
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.extraction.json_parser import parse_json_model
from app.models import QuestionTranslation, ResearchQuestion
from app.providers.llm.audit import record_ai_call
from app.providers.llm.base import LLMProvider, LLMResponse
from app.schemas.translations import QuestionTranslationSet

PROMPT_VERSION = "question-translation-v1"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "question_translation_v1.txt"


class QuestionTranslationService:
    def __init__(self, session: Session, provider: LLMProvider, model: str) -> None:
        self.session = session
        self.provider = provider
        self.model = model

    async def translate(self, questions: list[ResearchQuestion]) -> list[QuestionTranslation]:
        if not questions:
            return []
        payload = [
            {
                "question_id": q.id,
                "question": q.question,
                "economic_mechanism": q.economic_mechanism,
                "counter_mechanism": q.counter_mechanism,
                "required_data": q.required_data_json,
                "known_risks": q.known_risks_json,
            }
            for q in questions
        ]
        messages = [
            {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        schema = {
            "name": "question_translation_set",
            "strict": True,
            "schema": QuestionTranslationSet.model_json_schema(),
        }
        started = time.perf_counter()
        response: LLMResponse | None = None
        try:
            response = await self.provider.complete(
                model=self.model, messages=messages, response_schema=schema
            )
            result = parse_json_model(response.content, QuestionTranslationSet)
            expected_ids = {question.id for question in questions}
            returned_ids = {item.question_id for item in result.translations}
            if returned_ids != expected_ids:
                raise ValueError("Question translation IDs do not match requested questions")
            rows = [
                QuestionTranslation(
                    question_id=item.question_id,
                    question_zh=item.question_zh,
                    economic_mechanism_zh=item.economic_mechanism_zh,
                    counter_mechanism_zh=item.counter_mechanism_zh,
                    required_data_zh_json=item.required_data_zh,
                    known_risks_zh_json=item.known_risks_zh,
                    model=self.model,
                    prompt_version=PROMPT_VERSION,
                )
                for item in result.translations
            ]
            self.session.add_all(rows)
            record_ai_call(
                self.session,
                run_id=None,
                provider=self.provider,
                requested_model=self.model,
                prompt_version=PROMPT_VERSION,
                response=response,
                started=started,
                status="SUCCESS",
            )
            self.session.commit()
            return rows
        except Exception:
            self.session.rollback()
            record_ai_call(
                self.session,
                run_id=None,
                provider=self.provider,
                requested_model=self.model,
                prompt_version=PROMPT_VERSION,
                response=response,
                started=started,
                status="VALIDATION_ERROR" if response else "API_ERROR",
            )
            self.session.commit()
            raise
