import json
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.extraction.json_parser import parse_json_model
from app.models import ResearchQuestion, StrategyIncubation
from app.providers.llm.audit import record_ai_call
from app.providers.llm.base import LLMProvider, LLMResponse
from app.schemas.strategy import StrategyIncubationSpec

PROMPT_VERSION = "strategy-incubation-v1.2"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "strategy_incubation_v1.txt"


class StrategyIncubationService:
    def __init__(self, session: Session, provider: LLMProvider, model: str) -> None:
        self.session = session
        self.provider = provider
        self.model = model

    async def generate(
        self,
        question: ResearchQuestion,
        handoff_package: dict,
        run_id: str | None = None,
    ) -> StrategyIncubation:
        payload = {
            "research_handoff": handoff_package,
            "available_research_datasets": [],
            "system_constraint": (
                "QRI 当前没有连接行情、基本面、借券或 point-in-time 数据集；"
                "只能生成等待数据验证的规格。"
            ),
        }
        messages = [
            {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        response_schema = {
            "name": "strategy_incubation_spec",
            "strict": True,
            "schema": StrategyIncubationSpec.model_json_schema(),
        }
        started = time.perf_counter()
        response: LLMResponse | None = None
        try:
            response = await self.provider.complete(
                model=self.model,
                messages=messages,
                response_schema=response_schema,
            )
            result = parse_json_model(response.content, StrategyIncubationSpec)
            if result.readiness_status == "READY_FOR_BACKTEST":
                raise ValueError("No research datasets are connected; strategy cannot be ready")
            incubation = self.session.scalar(
                select(StrategyIncubation).where(
                    StrategyIncubation.question_id == question.id
                )
            )
            if incubation:
                incubation.readiness_status = result.readiness_status
                incubation.specification_json = result.model_dump(mode="json")
                incubation.model = self.model
                incubation.prompt_version = PROMPT_VERSION
            else:
                incubation = StrategyIncubation(
                    question_id=question.id,
                    readiness_status=result.readiness_status,
                    specification_json=result.model_dump(mode="json"),
                    model=self.model,
                    prompt_version=PROMPT_VERSION,
                )
                self.session.add(incubation)
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
            return incubation
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
