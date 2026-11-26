"""Configuration for the AI/insights layer.

Values are read once at import time. Tests may monkeypatch module attributes.
No provider SDK is imported here; Phase 3 owns the Groq client.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


AI_ENABLED = _env_bool("AI_ENABLED", False)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()
AI_MODEL = os.environ.get("AI_MODEL", "qwen/qwen3.8-27b").strip()
AI_TIMEOUT_SECONDS = _env_int("AI_TIMEOUT_SECONDS", 30)
AI_MAX_OUTPUT_TOKENS = _env_int("AI_MAX_OUTPUT_TOKENS", 1200)
AI_TEMPERATURE = _env_float("AI_TEMPERATURE", 0.2)
AI_SUMMARY_PROMPT_VERSION = os.environ.get("AI_SUMMARY_PROMPT_VERSION", "summary-v1")
AI_CHAT_PROMPT_VERSION = os.environ.get("AI_CHAT_PROMPT_VERSION", "chat-v1")
AI_SUMMARY_LIMIT_PER_HOUR = _env_int("AI_SUMMARY_LIMIT_PER_HOUR", 5)
AI_CHAT_LIMIT_PER_MINUTE = _env_int("AI_CHAT_LIMIT_PER_MINUTE", 10)
AI_CHAT_LIMIT_PER_DAY = _env_int("AI_CHAT_LIMIT_PER_DAY", 200)
AI_MAX_PERIOD_DAYS = _env_int("AI_MAX_PERIOD_DAYS", 366)
BUDGET_WARNING_THRESHOLD = _env_int("BUDGET_WARNING_THRESHOLD", 90)

AI_CONFIGURED = bool(AI_ENABLED and GROQ_API_KEY)
