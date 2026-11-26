"""State shapes for the LangGraph workflows."""
from typing import Any, TypedDict


class SummaryState(TypedDict, total=False):
    user_id: int
    preset: str
    date_from: str | None
    date_to: str | None
    force: bool
    prefs: dict[str, Any]
    period: Any
    facts: dict[str, Any]
    fingerprint: str
    cached: bool
    summary: dict[str, Any] | None
    validation_errors: list[str]
    attempts: int
    model: str
    prompt_version: str
    model_instance: Any
    usage: dict[str, int]
    degraded: bool
    status: str
    generated_at: str


class ChatState(TypedDict, total=False):
    user_id: int
    session_id: str
    message: str
    preset: str
    date_from: str | None
    date_to: str | None
    prefs: dict[str, Any]
    period: Any
    facts: dict[str, Any]
    history: list[dict[str, Any]]
    intent: str
    scope_ok: bool
    refusal: str
    tool_names: list[str]
    tool_results: dict[str, Any]
    answer: dict[str, Any]
    validation_errors: list[str]
    attempts: int
    model: str
    prompt_version: str
    model_instance: Any
    usage: dict[str, int]
    status: str
