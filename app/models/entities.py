import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class FullTextStatus(StrEnum):
    UNKNOWN = "UNKNOWN"
    ABSTRACT_ONLY = "ABSTRACT_ONLY"
    FULLTEXT_AVAILABLE = "FULLTEXT_AVAILABLE"
    FULLTEXT_UNAVAILABLE = "FULLTEXT_UNAVAILABLE"


class QuestionStatus(StrEnum):
    DISCOVERED = "DISCOVERED"
    AI_REVIEWED = "AI_REVIEWED"
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    REJECTED = "REJECTED"
    EXPORTED = "EXPORTED"


class Paper(Base):
    __tablename__ = "papers"
    id: Mapped[int] = mapped_column(primary_key=True)
    paper_uid: Mapped[str] = mapped_column(
        String(64), unique=True, default=lambda: f"P-{uuid.uuid4().hex}"
    )
    canonical_paper_id: Mapped[int | None] = mapped_column(ForeignKey("papers.id"))
    doi: Mapped[str | None] = mapped_column(String(512), index=True)
    arxiv_id: Mapped[str | None] = mapped_column(String(64), index=True)
    semantic_scholar_id: Mapped[str | None] = mapped_column(String(64), index=True)
    openalex_id: Mapped[str | None] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(Text)
    normalized_title: Mapped[str] = mapped_column(Text, index=True)
    abstract: Mapped[str | None] = mapped_column(Text)
    authors_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    publication_date: Mapped[date | None] = mapped_column(Date)
    venue: Mapped[str | None] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)
    pdf_url: Mapped[str | None] = mapped_column(Text)
    open_access: Mapped[bool | None] = mapped_column(Boolean)
    license: Mapped[str | None] = mapped_column(String(255))
    citation_count: Mapped[int | None] = mapped_column(Integer)
    research_scope: Mapped[str] = mapped_column(String(32), default="UNCLASSIFIED", index=True)
    scope_reason: Mapped[str | None] = mapped_column(Text)
    scope_confidence: Mapped[float | None] = mapped_column(Float)
    scope_version: Mapped[str | None] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    fulltext_status: Mapped[FullTextStatus] = mapped_column(
        Enum(FullTextStatus), default=FullTextStatus.UNKNOWN
    )
    fulltext_failure_reason: Mapped[str | None] = mapped_column(Text)
    fulltext_attempted_at: Mapped[datetime | None] = mapped_column(DateTime)
    raw_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    sources: Mapped[list["PaperSource"]] = relationship(cascade="all, delete-orphan")


class PaperVersion(Base):
    __tablename__ = "paper_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    version_paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), unique=True)
    relation: Mapped[str] = mapped_column(String(32), default="VERSION_OF")
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PaperSource(Base):
    __tablename__ = "paper_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    provider_id: Mapped[str] = mapped_column(String(512))
    raw_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    document_type: Mapped[str] = mapped_column(String(16))
    local_path: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(64))
    parsed_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResearchCard(Base):
    __tablename__ = "research_cards"
    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    market: Mapped[str | None] = mapped_column(String(255))
    asset_class: Mapped[str | None] = mapped_column(String(255))
    universe: Mapped[str | None] = mapped_column(Text)
    sample_start: Mapped[str | None] = mapped_column(String(64))
    sample_end: Mapped[str | None] = mapped_column(String(64))
    hypothesis: Mapped[str | None] = mapped_column(Text)
    mechanism: Mapped[str | None] = mapped_column(Text)
    counter_mechanism: Mapped[str | None] = mapped_column(Text)
    signal_definition: Mapped[str | None] = mapped_column(Text)
    formation_period: Mapped[str | None] = mapped_column(String(255))
    holding_period: Mapped[str | None] = mapped_column(String(255))
    rebalance_frequency: Mapped[str | None] = mapped_column(String(255))
    portfolio_construction: Mapped[str | None] = mapped_column(Text)
    benchmark: Mapped[str | None] = mapped_column(Text)
    reported_return: Mapped[str | None] = mapped_column(Text)
    reported_alpha: Mapped[str | None] = mapped_column(Text)
    reported_sharpe: Mapped[str | None] = mapped_column(Text)
    reported_max_drawdown: Mapped[str | None] = mapped_column(Text)
    transaction_cost_handling: Mapped[str | None] = mapped_column(Text)
    survivorship_handling: Mapped[str | None] = mapped_column(Text)
    lookahead_handling: Mapped[str | None] = mapped_column(Text)
    in_sample: Mapped[str | None] = mapped_column(Text)
    out_of_sample: Mapped[str | None] = mapped_column(Text)
    robustness_tests_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    required_data_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    limitations_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    confidence: Mapped[float | None] = mapped_column(Float)
    model: Mapped[str] = mapped_column(String(255))
    prompt_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AbstractBrief(Base):
    __tablename__ = "abstract_briefs"
    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), unique=True, index=True)
    summary_zh: Mapped[str] = mapped_column(Text)
    core_principle_zh: Mapped[str] = mapped_column(Text)
    economic_mechanism_zh: Mapped[str] = mapped_column(Text)
    methodology_zh: Mapped[str | None] = mapped_column(Text)
    reported_findings_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    limitations_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    reader_takeaway_zh: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    model: Mapped[str] = mapped_column(String(255))
    prompt_version: Mapped[str] = mapped_column(String(64))
    source_scope: Mapped[str] = mapped_column(String(32), default="TITLE_ABSTRACT")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Claim(Base):
    __tablename__ = "claims"
    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    claim_type: Mapped[str] = mapped_column(String(64), default="AUTHOR_CLAIM")
    claim_text: Mapped[str] = mapped_column(Text)
    normalized_claim: Mapped[str | None] = mapped_column(Text)
    direction: Mapped[str | None] = mapped_column(String(32))
    support_strength: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), index=True)
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id"), index=True)
    research_card_field: Mapped[str | None] = mapped_column(String(128))
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(512))
    paragraph_index: Mapped[int | None] = mapped_column(Integer)
    source_text: Mapped[str] = mapped_column(Text)
    start_offset: Mapped[int | None] = mapped_column(Integer)
    end_offset: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PaperComparison(Base):
    __tablename__ = "paper_comparisons"
    id: Mapped[int] = mapped_column(primary_key=True)
    comparison_uid: Mapped[str] = mapped_column(
        String(64), unique=True, default=lambda: f"CMP-{uuid.uuid4().hex}"
    )
    paper_ids_json: Mapped[list[int]] = mapped_column(JSON)
    common_findings_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    differences_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    contradictions_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    sample_differences_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    universe_differences_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    signal_differences_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    cost_assumption_differences_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    oos_differences_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    survivorship_differences_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    possible_explanations_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    research_gap: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(255))
    prompt_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResearchQuestion(Base):
    __tablename__ = "research_questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_uid: Mapped[str] = mapped_column(String(64), unique=True)
    family: Mapped[str] = mapped_column(String(128))
    question: Mapped[str] = mapped_column(Text)
    plain_language_question: Mapped[str | None] = mapped_column(Text)
    academic_question: Mapped[str | None] = mapped_column(Text)
    economic_mechanism: Mapped[str] = mapped_column(Text)
    counter_mechanism: Mapped[str] = mapped_column(Text)
    supporting_claims_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    contradicting_claims_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    required_data_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    known_risks_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    novelty_score: Mapped[float | None] = mapped_column(Float)
    testability_score: Mapped[float | None] = mapped_column(Float)
    data_availability_score: Mapped[float | None] = mapped_column(Float)
    research_priority_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[QuestionStatus] = mapped_column(
        Enum(QuestionStatus), default=QuestionStatus.HUMAN_REVIEW_REQUIRED
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class QuestionTranslation(Base):
    __tablename__ = "question_translations"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("research_questions.id"), unique=True, index=True
    )
    question_zh: Mapped[str] = mapped_column(Text)
    economic_mechanism_zh: Mapped[str] = mapped_column(Text)
    counter_mechanism_zh: Mapped[str] = mapped_column(Text)
    required_data_zh_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    known_risks_zh_json: Mapped[list[Any]] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(255))
    prompt_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class StrategyIncubation(Base):
    __tablename__ = "strategy_incubations"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("research_questions.id"), unique=True, index=True
    )
    readiness_status: Mapped[str] = mapped_column(String(32), default="WAITING_FOR_DATA")
    specification_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(255))
    prompt_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ResearchValidationSpec(Base):
    __tablename__ = "research_validation_specs"
    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("research_questions.id"), unique=True, index=True
    )
    review_status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    specification_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(255))
    prompt_version: Mapped[str] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, default=lambda: str(uuid.uuid4()))
    query: Mapped[str] = mapped_column(Text)
    run_type: Mapped[str] = mapped_column(String(32), default="END_TO_END")
    status: Mapped[str] = mapped_column(String(32), default="RUNNING")
    current_stage: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    deduplicated_count: Mapped[int] = mapped_column(Integer, default=0)
    fulltext_success_count: Mapped[int] = mapped_column(Integer, default=0)
    fulltext_failure_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_call_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    research_card_count: Mapped[int] = mapped_column(Integer, default=0)
    claim_count: Mapped[int] = mapped_column(Integer, default=0)
    question_count: Mapped[int] = mapped_column(Integer, default=0)


class PipelineStageRun(Base):
    __tablename__ = "pipeline_stage_runs"
    __table_args__ = (UniqueConstraint("run_id", "stage", name="uq_pipeline_stage_run"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    checkpoint_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AICall(Base):
    __tablename__ = "ai_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    requested_model: Mapped[str] = mapped_column(String(255))
    returned_model: Mapped[str | None] = mapped_column(String(255))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    prompt_version: Mapped[str] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int] = mapped_column(Integer)
    response_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
