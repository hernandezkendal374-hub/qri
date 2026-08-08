import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.evidence.locator import EvidenceLocation, EvidenceLocator, EvidenceNotFoundError
from app.extraction.json_parser import parse_json_model
from app.models import AICall, Claim, Document, Evidence, Paper, ResearchCard
from app.parsing.base import DocumentParser
from app.providers.llm.base import LLMProvider, LLMResponse
from app.schemas.claims import ClaimEvidenceExtraction, EvidenceQuote
from app.schemas.research import PaperResearchCard

PROMPT_VERSION = "claim-evidence-v1"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "claim_evidence_v1.txt"


@dataclass(slots=True)
class ClaimExtractionResult:
    claims_created: int
    evidence_created: int
    rejected_quotes: int


class ClaimEvidenceExtractor:
    def __init__(
        self,
        session: Session,
        provider: LLMProvider,
        parser: DocumentParser,
        model: str,
    ) -> None:
        self.session = session
        self.provider = provider
        self.parser = parser
        self.model = model

    async def extract(
        self,
        paper: Paper,
        document: Document,
        card: ResearchCard,
        run_id: str | None = None,
    ) -> ClaimExtractionResult:
        if document.document_type != "PDF" or not document.local_path or not document.parsed_text:
            raise ValueError("Claim extraction requires a local parsed PDF")
        parsed = self.parser.parse(Path(document.local_path))
        if parsed.text != document.parsed_text:
            raise ValueError("Stored parsed text differs from current parser output")
        locator = EvidenceLocator(parsed)
        messages = self._messages(paper, document, card)
        response_schema = {
            "name": "claim_evidence_extraction",
            "strict": True,
            "schema": ClaimEvidenceExtraction.model_json_schema(),
        }
        started = time.perf_counter()
        response: LLMResponse | None = None
        try:
            response = await self.provider.complete(
                model=self.model,
                messages=messages,
                response_schema=response_schema,
            )
            extraction = parse_json_model(response.content, ClaimEvidenceExtraction)
            result = self._persist(paper, card, extraction, locator)
            self._audit(run_id, response, started, "SUCCESS")
            self.session.commit()
            return result
        except Exception:
            self.session.rollback()
            self._audit(
                run_id,
                response,
                started,
                "PARSE_ERROR" if response else "API_ERROR",
            )
            self.session.commit()
            raise

    def _persist(
        self,
        paper: Paper,
        card: ResearchCard,
        extraction: ClaimEvidenceExtraction,
        locator: EvidenceLocator,
    ) -> ClaimExtractionResult:
        claims_created = 0
        evidence_created = 0
        rejected = 0
        for candidate in extraction.claims:
            located: list[tuple[EvidenceQuote, EvidenceLocation]] = []
            for quote in candidate.evidence:
                try:
                    located.append((quote, locator.locate(quote.source_text)))
                except EvidenceNotFoundError:
                    rejected += 1
            if not located:
                continue
            claim = Claim(
                paper_id=paper.id,
                claim_type="AUTHOR_CLAIM",
                claim_text=candidate.claim_text,
                normalized_claim=candidate.normalized_claim,
                direction=candidate.direction,
                support_strength=candidate.support_strength,
                confidence=candidate.confidence,
            )
            self.session.add(claim)
            self.session.flush()
            claims_created += 1
            for quote, location in located:
                self.session.add(self._evidence(paper.id, location, quote, claim_id=claim.id))
                evidence_created += 1
        for item in extraction.research_card_evidence:
            if item.research_card_field not in PaperResearchCard.model_fields:
                rejected += 1
                continue
            storage_field = {
                "robustness_tests": "robustness_tests_json",
                "required_data": "required_data_json",
                "limitations": "limitations_json",
            }.get(item.research_card_field, item.research_card_field)
            if not getattr(card, storage_field):
                rejected += 1
                continue
            try:
                location = locator.locate(item.evidence.source_text)
            except EvidenceNotFoundError:
                rejected += 1
                continue
            self.session.add(
                self._evidence(
                    paper.id,
                    location,
                    item.evidence,
                    research_card_field=item.research_card_field,
                )
            )
            evidence_created += 1
        return ClaimExtractionResult(claims_created, evidence_created, rejected)

    @staticmethod
    def _evidence(
        paper_id: int,
        location: EvidenceLocation,
        quote: EvidenceQuote,
        *,
        claim_id: int | None = None,
        research_card_field: str | None = None,
    ) -> Evidence:
        return Evidence(
            paper_id=paper_id,
            claim_id=claim_id,
            research_card_field=research_card_field,
            page_number=location.page_number,
            section=quote.section,
            paragraph_index=location.paragraph_index,
            source_text=location.source_text,
            start_offset=location.start_offset,
            end_offset=location.end_offset,
            confidence=quote.confidence,
        )

    @staticmethod
    def _messages(paper: Paper, document: Document, card: ResearchCard) -> list[dict[str, str]]:
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        card_data = {
            field: getattr(
                card,
                {
                    "robustness_tests": "robustness_tests_json",
                    "required_data": "required_data_json",
                    "limitations": "limitations_json",
                }.get(field, field),
            )
            for field in PaperResearchCard.model_fields
        }
        return [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    f"PAPER TITLE:\n{paper.title}\n\n"
                    f"RESEARCH CARD:\n{json.dumps(card_data, ensure_ascii=False)}\n\n"
                    f"FULL TEXT:\n{document.parsed_text}"
                ),
            },
        ]

    def _audit(
        self,
        run_id: str | None,
        response: LLMResponse | None,
        started: float,
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
                latency_ms=int((time.perf_counter() - started) * 1000),
                response_hash=hashlib.sha256(content.encode()).hexdigest() if content else None,
                status=status,
            )
        )
