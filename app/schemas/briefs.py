from pydantic import BaseModel, ConfigDict, Field


class AbstractBriefExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary_zh: str = Field(min_length=20)
    core_principle_zh: str = Field(min_length=20)
    economic_mechanism_zh: str = Field(min_length=20)
    methodology_zh: str | None = None
    reported_findings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(min_length=1)
    reader_takeaway_zh: str = Field(min_length=20)
    confidence: float = Field(ge=0, le=1)
