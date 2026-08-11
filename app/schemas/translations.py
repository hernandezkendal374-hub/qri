from pydantic import BaseModel, ConfigDict, Field


class QuestionTranslationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: int
    question_zh: str = Field(min_length=20)
    economic_mechanism_zh: str = Field(min_length=10)
    counter_mechanism_zh: str = Field(min_length=10)
    required_data_zh: list[str] = Field(min_length=1)
    known_risks_zh: list[str] = Field(min_length=1)


class QuestionTranslationSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    translations: list[QuestionTranslationItem] = Field(min_length=1)
