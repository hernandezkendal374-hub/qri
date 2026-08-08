import hashlib
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.extraction.json_parser import parse_json_model
from app.models import AICall, Document, Paper, ResearchCard
from app.providers.llm.base import LLMProvider, LLMResponse
from app.schemas.research import ResearchCardExtraction

PROMPT_VERSION = "research-card-v1"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "research_card_v1.txt"


class ResearchCardExtractor:
    def __init__(self, session: Session, provider: LLMProvider, model: str) -> None:
        self.session = session
        self.provider = provider
        self.model = model

    async def extract(
        self, paper: Paper, document: Document, run_id: str | None = None
    ) -> ResearchCard:
        if document.document_type != "PDF" or not document.parsed_text:
            raise ValueError("Research Card extraction requires parsed PDF full text")
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": f"PAPER TITLE:\n{paper.title}\n\nFULL TEXT:\n{document.parsed_text}",
            },
        ]
        schema = {
            "name": "paper_research_card",
            "strict": True,
            "schema": ResearchCardExtraction.model_json_schema(),
        }
        started = time.perf_counter()
        response: LLMResponse | None = None
        try:
            response = await self.provider.complete(
                model=self.model, messages=messages, response_schema=schema
            )
            extraction = parse_json_model(response.content, ResearchCardExtraction)
            card = self._to_model(paper.id, extraction)
            self.session.add(card)
            self._audit(
                run_id,
                response,
                int((time.perf_counter() - started) * 1000),
                "SUCCESS",
            )
            self.session.commit()
            return card
        except Exception:
            self.session.rollback()
            self._audit(
                run_id,
                response,
                int((time.perf_counter() - started) * 1000),
                "PARSE_ERROR" if response else "API_ERROR",
            )
            self.session.commit()
            raise

    def _to_model(self, paper_id: int, extraction: ResearchCardExtraction) -> ResearchCard:
        values = extraction.card.model_dump()
        values["robustness_tests_json"] = values.pop("robustness_tests")
        values["required_data_json"] = values.pop("required_data")
        values["limitations_json"] = values.pop("limitations")
        return ResearchCard(
            paper_id=paper_id,
            **values,
            confidence=None,
            model=self.model,
            prompt_version=PROMPT_VERSION,
        )

    def _audit(
        self,
        run_id: str | None,
        response: LLMResponse | None,
        latency_ms: int,
        status: str,
    ) -> None:
        content = response.content if response else ""
        self.session.add(
            AICall(
                run_id=run_id,
                provider=type(self.provider).__name__,
                requested_model=self.model,
                returned_model=response.returned_model if response else None,
                prompt_version=PROMPT_VERSION,
                input_tokens=response.input_tokens if response else None,
                output_tokens=response.output_tokens if response else None,
                estimated_cost=None,
                latency_ms=latency_ms,
                response_hash=hashlib.sha256(content.encode()).hexdigest() if content else None,
                status=status,
            )
        )
