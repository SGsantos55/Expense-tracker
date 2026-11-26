"""LangGraph workflow for scoped, tool-grounded chat answers."""
from langgraph.graph import END, START, StateGraph

from ai.analytics import build_facts
from ai.chat_policy import REFUSAL, classify_intent
from ai.config import AI_CHAT_PROMPT_VERSION, AI_MODEL
from ai.graphs.state import ChatState
from ai.llm import LLMUnavailable, invoke_chat
from ai.periods import PeriodError, resolve_period
from ai.tools import TOOLS_FOR_INTENT, build_tool_args, execute_tool
from ai.validation import build_chat_fallback, validate_chat_answer
from database.ai_queries import append_chat_messages, record_usage


def _guard_input(state: ChatState):
    message = str(state.get("message") or "").strip()
    if not message or len(message) > 500:
        return {
            "message": message[:500],
            "scope_ok": False,
            "refusal": REFUSAL,
            "status": "invalid_input",
        }
    return {"message": message}


def _classify_scope(state: ChatState):
    categories = (state.get("facts") or {}).get("expenses", {}).get("by_category") or []
    intent = classify_intent(state["message"], categories=categories)
    if not intent:
        return {
            "intent": "refusal",
            "scope_ok": False,
            "refusal": REFUSAL,
            "status": "refused",
        }
    return {"intent": intent, "scope_ok": True, "validation_errors": []}


def _resolve_period(state: ChatState):
    prefs = state.get("prefs") or {}
    try:
        period = resolve_period(
            state.get("preset", "this_month"),
            state.get("date_from"),
            state.get("date_to"),
            prefs=prefs,
        )
    except PeriodError:
        period = resolve_period("this_month", prefs=prefs)
    return {"period": period}


def _compute_facts(state: ChatState):
    facts = dict(build_facts(state["user_id"], state["period"], state.get("prefs") or {}))
    facts["prefs"] = dict(state.get("prefs") or {})
    return {"facts": facts}


def _route_tools(state: ChatState):
    return {"tool_names": list(TOOLS_FOR_INTENT.get(state["intent"], ()))}


def _execute_tools(state: ChatState):
    results = {}
    for name in state.get("tool_names", []):
        args = build_tool_args(state["intent"], state["message"], state["facts"])
        try:
            results[name] = execute_tool(
                name, args, state["user_id"], state["period"], state["facts"]
            )
        except Exception as exc:
            results[name] = {"available": False, "error": type(exc).__name__}
    return {"tool_results": results}


def _compose_answer(state: ChatState):
    attempts = state.get("attempts", 0) + 1
    try:
        answer, usage = invoke_chat(
            state["message"],
            state["facts"],
            state.get("tool_results") or {},
            history=state.get("history") or [],
            validation_errors=state.get("validation_errors") or [],
            model=state.get("model_instance"),
        )
    except LLMUnavailable:
        return {
            "attempts": attempts,
            "answer": build_chat_fallback(
                state["message"],
                state["facts"],
                state.get("tool_results") or {},
                state.get("scope_ok", True),
                state.get("intent"),
                state.get("refusal", REFUSAL),
            ),
            "degraded": True,
            "status": "disabled",
            "validation_errors": [],
            "usage": {},
        }
    except Exception as exc:
        return {
            "attempts": attempts,
            "answer": None,
            "status": "parse_error",
            "validation_errors": [type(exc).__name__],
            "usage": {},
        }
    return {
        "attempts": attempts,
        "answer": answer,
        "status": "generated",
        "validation_errors": [],
        "usage": usage,
    }


def _validate_answer(state: ChatState):
    answer = state.get("answer")
    if not answer:
        return {
            "validation_errors": state.get("validation_errors") or ["Answer missing."],
            "status": "invalid",
        }
    errors = validate_chat_answer(
        answer,
        state["message"],
        state["facts"],
        state.get("tool_results") or {},
        scope_ok=state.get("scope_ok", True),
        refusal=state.get("refusal", REFUSAL),
    )
    if errors:
        return {"validation_errors": errors, "status": "invalid"}
    return {"validation_errors": [], "status": "generated"}


def _fallback(state: ChatState):
    status = state.get("status")
    if status not in {"disabled", "refused", "invalid_input"}:
        status = "fallback"
    return {
        "answer": build_chat_fallback(
            state["message"],
            state.get("facts") or {},
            state.get("tool_results") or {},
            state.get("scope_ok", True),
            state.get("intent"),
            state.get("refusal", REFUSAL),
        ),
        "degraded": True,
        "status": status,
        "validation_errors": [],
    }


def _persist_messages(state: ChatState):
    answer = state.get("answer") or {"answer": REFUSAL, "follow_up_suggestions": []}
    append_chat_messages(
        state["session_id"],
        state["user_id"],
        [
            {"role": "user", "content": state["message"]},
            {"role": "assistant", "content": answer["answer"]},
        ],
    )
    usage = state.get("usage") or {}
    record_usage(
        state["user_id"],
        "chat",
        state.get("model"),
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        usage.get("latency_ms", 0),
    )
    return {"answer": answer}


def _after_guard(state: ChatState):
    return "fallback" if state.get("status") == "invalid_input" else "continue"


def _after_scope(state: ChatState):
    return "grounded" if state.get("scope_ok") else "fallback"


def _after_compose(state: ChatState):
    return "fallback" if state.get("degraded") else "validate"


def _after_validation(state: ChatState):
    if state.get("status") == "generated":
        return "persist"
    if state.get("attempts", 0) < 2:
        return "retry"
    return "fallback"


def _build_graph():
    graph = StateGraph(ChatState)
    graph.add_node("guard_input", _guard_input)
    graph.add_node("classify_scope", _classify_scope)
    graph.add_node("resolve_period", _resolve_period)
    graph.add_node("compute_facts", _compute_facts)
    graph.add_node("route_tools", _route_tools)
    graph.add_node("execute_tools", _execute_tools)
    graph.add_node("compose_answer", _compose_answer)
    graph.add_node("validate_answer", _validate_answer)
    graph.add_node("fallback", _fallback)
    graph.add_node("persist_messages", _persist_messages)

    graph.add_edge(START, "guard_input")
    graph.add_conditional_edges(
        "guard_input", _after_guard, {"continue": "resolve_period", "fallback": "fallback"}
    )
    graph.add_edge("resolve_period", "compute_facts")
    graph.add_edge("compute_facts", "classify_scope")
    graph.add_conditional_edges(
        "classify_scope", _after_scope, {"grounded": "route_tools", "fallback": "fallback"}
    )
    graph.add_edge("route_tools", "execute_tools")
    graph.add_edge("execute_tools", "compose_answer")
    graph.add_conditional_edges(
        "compose_answer",
        _after_compose,
        {"validate": "validate_answer", "fallback": "fallback"},
    )
    graph.add_conditional_edges(
        "validate_answer",
        _after_validation,
        {"retry": "compose_answer", "persist": "persist_messages", "fallback": "fallback"},
    )
    graph.add_edge("fallback", "persist_messages")
    graph.add_edge("persist_messages", END)
    return graph.compile()


CHAT_GRAPH = _build_graph()


def run_chat_graph(state: ChatState, model=None):
    initial = dict(state)
    initial.setdefault("model", AI_MODEL)
    initial.setdefault("prompt_version", AI_CHAT_PROMPT_VERSION)
    initial.setdefault("attempts", 0)
    if model is not None:
        initial["model_instance"] = model
    return CHAT_GRAPH.invoke(initial)
