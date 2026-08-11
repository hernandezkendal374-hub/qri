import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.extraction.json_parser import parse_json_model
from app.models import AbstractBrief, Paper
from app.providers.llm.audit import record_ai_call
from app.providers.llm.base import LLMProvider, LLMResponse
from app.schemas.briefs import AbstractBriefExtraction

PROMPT_VERSION = "abstract-brief-v1"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "abstract_brief_v1.txt"


class AbstractBriefExtractor:
    def __init__(self, session: Session, provider: LLMProvider, model: str) -> None:
        self.session = session
        self.provider = provider
        self.model = model

    async def extract(self, paper: Paper, run_id: str | None = None) -> AbstractBrief:
        if not paper.abstract:
            raise ValueError("Abstract Brief requires a paper abstract")
        messages = [
            {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
            {
                "role": "user",
                "content": f"论文标题：\n{paper.title}\n\n论文摘要：\n{paper.abstract}",
            },
        ]
        schema = {
            "name": "abstract_brief",
            "strict": True,
            "schema": AbstractBriefExtraction.model_json_schema(),
        }
        started = time.perf_counter()
        response: LLMResponse | None = None
        try:
            response = await self.provider.complete(
                model=self.model, messages=messages, response_schema=schema
            )
            result = parse_json_model(response.content, AbstractBriefExtraction)
            brief = AbstractBrief(
                paper_id=paper.id,
                summary_zh=result.summary_zh,
                core_principle_zh=result.core_principle_zh,
                economic_mechanism_zh=result.economic_mechanism_zh,
                methodology_zh=result.methodology_zh,
                reported_findings_json=result.reported_findings,
                limitations_json=result.limitations,
                reader_takeaway_zh=result.reader_takeaway_zh,
                confidence=result.confidence,
                model=self.model,
                prompt_version=PROMPT_VERSION,
            )
            self.session.add(brief)
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
            return brief
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
