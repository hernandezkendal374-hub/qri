from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_text: str = Field(min_length=1)
    section: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class AuthorClaimCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_type: Literal["AUTHOR_CLAIM"]
    claim_text: str = Field(min_length=1)
    normalized_claim: str | None = None
    direction: Literal["POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL", "UNKNOWN"] | None = None
    support_strength: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: list[EvidenceQuote] = Field(min_length=1)


class ResearchCardFieldEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    research_card_field: str
    evidence: EvidenceQuote


class ClaimEvidenceExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[AuthorClaimCandidate] = Field(default_factory=list)
    research_card_evidence: list[ResearchCardFieldEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_output(self) -> "ClaimEvidenceExtraction":
        if not self.claims and not self.research_card_evidence:
            raise ValueError("At least one claim or Research Card evidence item is required")
        return self
