"""Public API used by Flask routes for the insights page and summaries."""
from ai.analytics import build_facts
from ai.config import AI_MODEL, AI_SUMMARY_LIMIT_PER_HOUR, AI_SUMMARY_PROMPT_VERSION
from ai.fingerprint import compute_data_fingerprint
from ai.graphs.chat_graph import run_chat_graph
from ai.graphs.summary_graph import run_summary_graph
from ai.llm import get_chat_model, is_available
from ai.periods import PeriodError, resolve_period
from ai.rate_limit import RateLimitError, check_chat_limits
from database.ai_queries import (
    chat_session_exists,
    count_recent_usage,
    create_chat_session,
    delete_chat_session,
    get_cached_summary,
    get_chat_history,
)
from database.settings_queries import get_user_preferences


class SummaryRateLimit(RuntimeError):
    """Raised when a user has generated too many summaries in one hour."""


def resolve_insights_period(preset, date_from, date_to, prefs, today=None):
    """Resolve a page period, falling back to this_month with a user message."""
    try:
        period = resolve_period(
            preset, date_from, date_to, prefs=prefs, today=today
        )
        return period, None
    except PeriodError as exc:
        return (
            resolve_period("this_month", prefs=prefs, today=today),
            f"{exc} Using this month instead.",
        )


def _period_params(preset, period):
    params = {"preset": preset}
    if preset == "custom":
        params["date_from"] = period.start.isoformat()
        params["date_to"] = period.end.isoformat()
    return params


def build_page_context(user_id, preset, date_from, date_to, today=None):
    """Build deterministic page data. Never calls an LLM."""
    prefs = get_user_preferences(user_id) or {}
    period, error = resolve_insights_period(
        preset, date_from, date_to, prefs, today=today
    )
    facts = build_facts(user_id, period, prefs)
    fingerprint = compute_data_fingerprint(
        user_id, prefs, AI_SUMMARY_PROMPT_VERSION, AI_MODEL
    )
    cached = get_cached_summary(
        user_id,
        period.start.isoformat(),
        period.end.isoformat(),
        AI_SUMMARY_PROMPT_VERSION,
        AI_MODEL,
        fingerprint,
    )
    return {
        "prefs": prefs,
        "period": period,
        "period_error": error,
        "period_params": _period_params(period.preset, period),
        "facts": facts,
        "fingerprint": fingerprint,
        "cached_summary": cached,
        "ai_available": is_available(),
        "model": AI_MODEL,
        "prompt_version": AI_SUMMARY_PROMPT_VERSION,
    }


def generate_summary_for_user(
    user_id, preset, date_from, date_to, force=False, model=None, today=None
):
    """Return a cached, generated or deterministic-fallback summary."""
    context = build_page_context(user_id, preset, date_from, date_to, today=today)
    if context["cached_summary"] and not force:
        return {
            **context,
            "summary": context["cached_summary"]["summary"],
            "degraded": bool(context["cached_summary"]["summary"].get("degraded")),
            "status": "cached",
            "generated_at": context["cached_summary"]["generated_at"],
        }

    usage_count = count_recent_usage(user_id, "summary", minutes=60)
    if usage_count >= AI_SUMMARY_LIMIT_PER_HOUR:
        raise SummaryRateLimit("Summary limit reached for this hour.")

    injected_model = model
    if injected_model is None and is_available():
        injected_model = get_chat_model()

    result = run_summary_graph(
        {
            "user_id": user_id,
            "preset": context["period"].preset,
            "date_from": None if context["period"].preset != "custom" else context["period"].start.isoformat(),
            "date_to": None if context["period"].preset != "custom" else context["period"].end.isoformat(),
            "force": True,
            "prefs": context["prefs"],
            "period": context["period"],
            "facts": context["facts"],
            "fingerprint": context["fingerprint"],
            "model": AI_MODEL,
            "prompt_version": AI_SUMMARY_PROMPT_VERSION,
            "attempts": 0,
        },
        model=injected_model,
    )
    return {
        **context,
        "summary": result.get("summary"),
        "degraded": bool(result.get("degraded")),
        "status": result.get("status"),
        "generated_at": result.get("generated_at"),
    }


class ChatUnavailable(RuntimeError):
    """Raised when chat is requested while AI is disabled."""


class ChatRateLimit(RuntimeError):
    """Raised when a user exceeds a chat quota."""


def chat_enabled():
    return is_available()


def ensure_chat_session(user_id, session_id=None):
    if session_id and chat_session_exists(session_id, user_id):
        return session_id
    return create_chat_session(user_id)


def get_chat_page_context(user_id, session_id=None):
    return {
        "available": chat_enabled(),
        "history": get_chat_history(session_id, user_id, limit=20) if session_id else [],
    }


def run_chat(user_id, session_id, message, preset, date_from, date_to, model=None):
    if not chat_enabled() and model is None:
        raise ChatUnavailable("AI chat is not configured.")

    try:
        check_chat_limits(user_id)
    except RateLimitError as exc:
        raise ChatRateLimit(str(exc)) from exc

    session_id = ensure_chat_session(user_id, session_id)
    prefs = get_user_preferences(user_id) or {}
    period, error = resolve_insights_period(preset, date_from, date_to, prefs)
    result = run_chat_graph(
        {
            "user_id": user_id,
            "session_id": session_id,
            "message": message,
            "preset": period.preset,
            "date_from": date_from if period.preset == "custom" else None,
            "date_to": date_to if period.preset == "custom" else None,
            "prefs": prefs,
            "period": period,
            "history": get_chat_history(session_id, user_id, limit=20),
            "tool_results": {},
            "attempts": 0,
        },
        model=model,
    )
    return {
        "session_id": session_id,
        "answer": result["answer"]["answer"],
        "follow_up_suggestions": result["answer"].get("follow_up_suggestions", []),
        "period": period.to_dict(),
        "status": result.get("status"),
        "degraded": bool(result.get("degraded")),
        "period_error": error,
    }


def clear_chat(user_id, session_id=None):
    if session_id:
        delete_chat_session(session_id, user_id)
