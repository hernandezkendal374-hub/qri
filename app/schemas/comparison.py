from pydantic import BaseModel, ConfigDict, Field, model_validator


class ComparisonItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=1)
    claim_ids: list[int] = Field(min_length=1)


class MultiPaperComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    common_findings: list[ComparisonItem] = Field(default_factory=list)
    differences: list[ComparisonItem] = Field(default_factory=list)
    contradictions: list[ComparisonItem] = Field(default_factory=list)
    sample_differences: list[ComparisonItem] = Field(default_factory=list)
    universe_differences: list[ComparisonItem] = Field(default_factory=list)
    signal_differences: list[ComparisonItem] = Field(default_factory=list)
    cost_assumption_differences: list[ComparisonItem] = Field(default_factory=list)
    oos_differences: list[ComparisonItem] = Field(default_factory=list)
    survivorship_differences: list[ComparisonItem] = Field(default_factory=list)
    possible_explanations: list[ComparisonItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_analysis(self) -> "MultiPaperComparison":
        if not any(getattr(self, field) for field in type(self).model_fields):
            raise ValueError("Comparison cannot be empty")
        return self


class CandidateQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family: str = Field(min_length=1)
    question: str = Field(min_length=20)
    economic_mechanism: str = Field(min_length=1)
    counter_mechanism: str = Field(min_length=1)
    supporting_claim_ids: list[int] = Field(min_length=1)
    contradicting_claim_ids: list[int] = Field(default_factory=list)
    required_data: list[str] = Field(min_length=1)
    known_risks: list[str] = Field(min_length=1)
    novelty_score: float = Field(ge=0, le=1)
    testability_score: float = Field(ge=0, le=1)
    data_availability_score: float = Field(ge=0, le=1)
    research_priority_score: float = Field(ge=0, le=1)


class CandidateQuestionSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    research_gap: str = Field(min_length=1)
    questions: list[CandidateQuestion] = Field(min_length=1, max_length=3)
