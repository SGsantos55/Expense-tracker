"""LangGraph workflow for cached, validated financial summaries."""
from langgraph.graph import END, START, StateGraph

from ai.analytics import build_facts
from ai.config import AI_MODEL, AI_SUMMARY_PROMPT_VERSION
from ai.fingerprint import compute_data_fingerprint
from ai.graphs.state import SummaryState
from ai.llm import LLMUnavailable, SummaryParseError, invoke_summary
from ai.periods import PeriodError, resolve_period
from ai.validation import build_fallback_summary, validate_summary
from database.ai_queries import get_cached_summary, record_usage, save_summary
from database.settings_queries import get_user_preferences


def _resolve_period(state: SummaryState):
    if state.get("period"):
        return {}
    prefs = state.get("prefs") or get_user_preferences(state["user_id"]) or {}
    try:
        period = resolve_period(
            state.get("preset", "this_month"),
            state.get("date_from"),
            state.get("date_to"),
            prefs=prefs,
        )
    except PeriodError:
        period = resolve_period("this_month", prefs=prefs)
    return {"period": period, "prefs": prefs}


def _load_context(state: SummaryState):
    updates = {}
    if not state.get("prefs"):
        updates["prefs"] = get_user_preferences(state["user_id"]) or {}
    updates.setdefault("model", AI_MODEL)
    updates.setdefault("prompt_version", AI_SUMMARY_PROMPT_VERSION)
    return updates


def _compute_facts(state: SummaryState):
    if state.get("facts"):
        return {}
    facts = build_facts(state["user_id"], state["period"], state.get("prefs") or {})
    return {"facts": facts, "insights": facts["insights"]}


def _check_cache(state: SummaryState):
    if state.get("force") or state.get("cached"):
        return {}
    fingerprint = state.get("fingerprint") or compute_data_fingerprint(
        state["user_id"],
        state.get("prefs") or {},
        state["prompt_version"],
        state["model"],
    )
    cached = get_cached_summary(
        state["user_id"],
        state["period"].start.isoformat(),
        state["period"].end.isoformat(),
        state["prompt_version"],
        state["model"],
        fingerprint,
    )
    if cached:
        return {
            "fingerprint": fingerprint,
            "cached": True,
            "summary": cached["summary"],
            "degraded": bool(cached["summary"].get("degraded")),
            "generated_at": cached["generated_at"],
            "status": "cached",
        }
    return {"fingerprint": fingerprint}


def _generate_summary(state: SummaryState):
    attempts = state.get("attempts", 0) + 1
    errors = state.get("validation_errors") or []
    try:
        summary, usage = invoke_summary(
            state["facts"],
            validation_errors=errors,
            model=state.get("model_instance"),
        )
    except LLMUnavailable:
        return {
            "attempts": attempts,
            "summary": build_fallback_summary(state["facts"]),
            "degraded": True,
            "status": "disabled",
            "validation_errors": [],
            "usage": {},
        }
    except SummaryParseError as exc:
        return {
            "attempts": attempts,
            "summary": None,
            "status": "parse_error",
            "validation_errors": [str(exc)],
            "usage": {},
        }
    except Exception as exc:
        return {
            "attempts": attempts,
            "summary": build_fallback_summary(state["facts"]),
            "degraded": True,
            "status": "provider_error",
            "validation_errors": [type(exc).__name__],
            "usage": {},
        }
    return {
        "attempts": attempts,
        "summary": summary,
        "status": "generated",
        "degraded": False,
        "validation_errors": [],
        "usage": usage,
    }


def _validate_summary(state: SummaryState):
    if state.get("degraded") or state.get("cached"):
        return {}
    summary = state.get("summary")
    if not summary:
        return {
            "validation_errors": state.get("validation_errors") or ["Summary output missing."],
            "status": "invalid",
        }
    errors = validate_summary(summary, state["facts"])
    if errors:
        return {"validation_errors": errors, "status": "invalid"}
    return {"validation_errors": [], "status": "generated"}


def _fallback(state: SummaryState):
    status = state.get("status")
    if status not in {"disabled", "provider_error"}:
        status = "fallback"
    return {
        "summary": build_fallback_summary(state["facts"]),
        "degraded": True,
        "status": status,
    }


def _persist(state: SummaryState):
    summary_payload = dict(state["summary"] or {})
    summary_payload["degraded"] = bool(state.get("degraded"))
    generated_at = save_summary(
        state["user_id"],
        state["period"].preset,
        state["period"].start.isoformat(),
        state["period"].end.isoformat(),
        state["facts"],
        summary_payload,
        state["fingerprint"],
        state["prompt_version"],
        state["model"],
    )
    usage = state.get("usage") or {}
    record_usage(
        state["user_id"],
        "summary",
        state["model"],
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        usage.get("latency_ms", 0),
    )
    return {"generated_at": generated_at}


def _after_cache(state: SummaryState):
    return "cached" if state.get("cached") else "generate"


def _after_generate(state: SummaryState):
    if state.get("degraded"):
        return "fallback"
    return "validate"


def _after_validation(state: SummaryState):
    if state.get("status") == "generated":
        return "persist"
    if state.get("attempts", 0) < 2:
        return "retry"
    return "fallback"


def _build_graph():
    graph = StateGraph(SummaryState)
    graph.add_node("resolve_period", _resolve_period)
    graph.add_node("load_context", _load_context)
    graph.add_node("compute_facts", _compute_facts)
    graph.add_node("check_cache", _check_cache)
    graph.add_node("generate_summary", _generate_summary)
    graph.add_node("validate_summary", _validate_summary)
    graph.add_node("fallback", _fallback)
    graph.add_node("persist", _persist)

    graph.add_edge(START, "resolve_period")
    graph.add_edge("resolve_period", "load_context")
    graph.add_edge("load_context", "compute_facts")
    graph.add_edge("compute_facts", "check_cache")
    graph.add_conditional_edges(
        "check_cache", _after_cache, {"cached": END, "generate": "generate_summary"}
    )
    graph.add_conditional_edges(
        "generate_summary",
        _after_generate,
        {"validate": "validate_summary", "fallback": "fallback"},
    )
    graph.add_conditional_edges(
        "validate_summary",
        _after_validation,
        {"retry": "generate_summary", "persist": "persist", "fallback": "fallback"},
    )
    graph.add_edge("fallback", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


SUMMARY_GRAPH = _build_graph()


def run_summary_graph(state: SummaryState, model=None):
    """Run the summary graph with an optional injected chat model."""
    initial = dict(state)
    if model is not None:
        initial["model_instance"] = model
    return SUMMARY_GRAPH.invoke(initial)
