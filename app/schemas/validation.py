from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VariableDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    role: Literal["DEPENDENT", "INDEPENDENT", "INTERACTION", "CONTROL"]
    academic_definition: str = Field(min_length=1)
    measurement: str = Field(min_length=1)
    timing_rule: str = Field(min_length=1)
    source_requirement: str = Field(min_length=1)


class ResearchValidationSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plain_language_question: str = Field(min_length=10)
    academic_question: str = Field(min_length=20)
    research_object: str = Field(min_length=1)
    economic_mechanism: str = Field(min_length=1)
    counter_mechanism: str = Field(min_length=1)
    dependent_variable: VariableDefinition
    independent_variables: list[VariableDefinition] = Field(min_length=1)
    interaction_terms: list[VariableDefinition]
    control_variables: list[VariableDefinition]
    sample_design: list[str] = Field(min_length=1)
    point_in_time_requirements: list[str] = Field(min_length=1)
    statistical_tests: list[str] = Field(min_length=1)
    out_of_sample_design: list[str] = Field(min_length=1)
    falsification_conditions: list[str] = Field(min_length=1)
    minimum_data_requirements: list[str] = Field(min_length=1)
    bias_risks: list[str] = Field(min_length=1)
    implementation_sensitivities: list[str]
    success_criteria: list[str] = Field(min_length=1)
    human_review_questions: list[str] = Field(min_length=1)
    prohibited_interpretations: list[str] = Field(min_length=1)
