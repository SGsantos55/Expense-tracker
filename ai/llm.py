"""Provider-specific Groq wrapper. No other module imports Groq directly."""
import json
import time

from langchain_groq import ChatGroq

import ai.config as config
from ai.prompts import build_chat_messages, build_summary_messages
from ai.schemas import ChatAnswer, FinancialSummary


class LLMUnavailable(RuntimeError):
    """Raised when AI is disabled or no provider key is configured."""


class SummaryParseError(RuntimeError):
    """Raised when the provider output cannot be parsed into the schema."""


def is_available():
    return bool(config.AI_ENABLED and config.GROQ_API_KEY)


def get_chat_model():
    if not is_available():
        raise LLMUnavailable("AI is disabled or no Groq API key is configured.")
    return ChatGroq(
        model=config.AI_MODEL,
        api_key=config.GROQ_API_KEY,
        temperature=config.AI_TEMPERATURE,
        timeout=config.AI_TIMEOUT_SECONDS,
        max_tokens=config.AI_MAX_OUTPUT_TOKENS,
    )


def _extract_json(content):
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            text = text.split("\n", 1)[1]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise SummaryParseError("AI response did not contain a JSON object.")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SummaryParseError(f"AI response was not valid JSON: {exc}") from exc


def _usage_from(response):
    usage = {}
    metadata = getattr(response, "response_metadata", None) or {}
    if isinstance(metadata, dict):
        usage = metadata.get("token_usage") or {}
    usage_metadata = getattr(response, "usage_metadata", None)
    if usage_metadata:
        usage = {
            "input_tokens": usage_metadata.get("input_tokens", 0),
            "output_tokens": usage_metadata.get("output_tokens", 0),
        }
    return {
        "input_tokens": int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
        "output_tokens": int(
            usage.get("output_tokens") or usage.get("completion_tokens") or 0
        ),
    }


def invoke_summary(facts, validation_errors=None, model=None):
    """Call the configured chat model once and return a parsed summary."""
    chat = model or get_chat_model()
    messages = build_summary_messages(facts, validation_errors=validation_errors)
    started = time.monotonic()
    response = chat.invoke(messages)
    usage = _usage_from(response)
    usage["latency_ms"] = int((time.monotonic() - started) * 1000)

    payload = _extract_json(getattr(response, "content", ""))
    try:
        summary = FinancialSummary.model_validate(payload).model_dump()
    except Exception as exc:
        raise SummaryParseError(f"AI summary failed schema validation: {exc}") from exc
    return summary, usage


def invoke_chat(message, facts, tool_results, history=None, validation_errors=None, model=None):
    """Call the configured chat model once and return a parsed chat answer."""
    chat = model or get_chat_model()
    messages = build_chat_messages(
        message,
        facts,
        tool_results,
        history=history,
        validation_errors=validation_errors,
    )
    started = time.monotonic()
    response = chat.invoke(messages)
    usage = _usage_from(response)
    usage["latency_ms"] = int((time.monotonic() - started) * 1000)

    payload = _extract_json(getattr(response, "content", ""))
    try:
        answer = ChatAnswer.model_validate(payload).model_dump()
    except Exception as exc:
        raise SummaryParseError(f"AI chat answer failed schema validation: {exc}") from exc
    return answer, usage
