"""Validated output shape for Phase 3 summaries."""
from pydantic import BaseModel, ConfigDict, Field


class Recommendation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    insight_id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class FinancialSummary(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    overview: str = Field(min_length=1)
    key_findings: list[str] = Field(default_factory=list, max_length=5)
    budget_analysis: str = Field(min_length=1)
    category_analysis: list[str] = Field(default_factory=list, max_length=5)
    recommendations: list[Recommendation] = Field(default_factory=list, max_length=3)
    warnings: list[str] = Field(default_factory=list, max_length=3)


class ChatAnswer(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    answer: str = Field(min_length=1, max_length=1200)
    follow_up_suggestions: list[str] = Field(default_factory=list, max_length=3)
