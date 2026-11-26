"""Validation and deterministic fallback for AI summaries."""
import re
from decimal import Decimal

from pydantic import ValidationError

from ai.chat_policy import REFUSAL, follow_up_suggestions
from ai.formatting import format_percent
from ai.schemas import ChatAnswer, FinancialSummary

MONEY_CLAIM = re.compile(r"(?:Rs|A\$|C\$|\$|€|£|₹)\s*([0-9][0-9.,]*[0-9]|[0-9])")
PERCENT_CLAIM = re.compile(r"([0-9]+(?:[.,][0-9]+)?)\s*%")
BANNED_ADVICE = re.compile(
    r"\b(invest(?:ment|ing|or)?|stock|shares?|crypto|loan|mortgage|borrow|"
    r"tax|legal|medical|doctor|guarantee(?:d)?|risk[- ]free|sure thing|"
    r"coding|programming|news|weather)\b",
    re.IGNORECASE,
)
CAUTIOUS_PHRASES = (
    "consider",
    "you could",
    "you might",
    "based on your data",
    "try",
    "review",
    "track",
    "compare",
    "set a",
)


def _as_dict(summary):
    if isinstance(summary, FinancialSummary):
        return summary.model_dump()
    if isinstance(summary, dict):
        return summary
    return None


def _iter_numbers(value):
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float, Decimal)):
        yield float(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_numbers(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_numbers(item)


def _parse_number(token, prefs):
    token = (token or "").strip().replace(" ", "")
    number_format = prefs.get("number_format", "1,234.56")
    if "," in token and "." in token:
        if number_format == "1.234,56":
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        if number_format == "1.234,56":
            token = token.replace(",", ".")
        else:
            token = token.replace(",", "")
    try:
        return float(token)
    except ValueError:
        return None


def _is_allowed(value, allowed, tolerance=0.011):
    return value is not None and any(abs(value - item) <= tolerance for item in allowed)


def _all_text(summary):
    values = [summary.get("overview", ""), summary.get("budget_analysis", "")]
    values.extend(summary.get("key_findings") or [])
    values.extend(summary.get("category_analysis") or [])
    values.extend(summary.get("warnings") or [])
    for recommendation in summary.get("recommendations") or []:
        if isinstance(recommendation, dict):
            values.append(recommendation.get("text", ""))
    return [str(value) for value in values if value]


def validate_summary(summary, facts):
    """Return validation errors; an empty list means the summary is safe to show."""
    payload = _as_dict(summary)
    if payload is None:
        return ["Summary output must be a JSON object."]
    try:
        parsed = FinancialSummary.model_validate(payload).model_dump()
    except ValidationError as exc:
        return [f"Invalid summary structure ({len(exc.errors())} issue(s))."]

    errors = []
    texts = _all_text(parsed)
    combined = " ".join(texts)

    if BANNED_ADVICE.search(combined):
        errors.append("Summary includes advice outside recorded spending data.")

    known_ids = {
        insight.get("id")
        for insight in facts.get("insights", [])
        if isinstance(insight, dict)
    }
    for recommendation in parsed["recommendations"]:
        insight_id = recommendation["insight_id"]
        if insight_id not in known_ids:
            errors.append(f"Recommendation references unknown insight '{insight_id}'.")
        if not any(phrase in recommendation["text"].lower() for phrase in CAUTIOUS_PHRASES):
            errors.append("Recommendations must use cautious language.")

    prefs = {
        "number_format": facts.get("formats", {}).get("number_format", "1,234.56")
    }
    allowed_numbers = set(_iter_numbers(facts))
    for text in texts:
        for match in MONEY_CLAIM.finditer(text):
            value = _parse_number(match.group(1), prefs)
            if not _is_allowed(value, allowed_numbers):
                errors.append("Summary contains a monetary figure not found in facts.")
        for match in PERCENT_CLAIM.finditer(text):
            value = _parse_number(match.group(1), prefs)
            if not _is_allowed(value, allowed_numbers, tolerance=0.1):
                errors.append("Summary contains a percentage not found in facts.")

    return list(dict.fromkeys(errors))


def build_fallback_summary(facts):
    """Build a cautious deterministic narrative from facts and rule insights."""
    period_label = facts["period"]["label"]
    income = facts["income"]
    expenses = facts["expenses"]
    budget = facts["budget"]
    insights = facts.get("insights") or []

    overview = (
        f"For {period_label}, you recorded {income['display']} of income and "
        f"{expenses['display_total']} of spending."
    )
    if budget["status"] == "no_budget":
        overview += " No overall budget is set for this period."
    else:
        overview += f" Your remaining overall budget is {budget['display_remaining']}."

    if budget["status"] == "no_budget":
        budget_analysis = "Set an overall budget to see how this period compares with your plan."
    else:
        budget_analysis = (
            f"You have used {format_percent(budget['utilisation'])} of your "
            f"{budget['display_allowance']} allowance for this period."
        )

    category_analysis = [
        f"{row['name']}: {row['display']} ({format_percent(row['share'])} of spending)."
        for row in expenses["by_category"][:5]
    ]
    if not category_analysis:
        category_analysis = ["No spending was recorded in this period."]

    actionable = [
        insight for insight in insights if insight.get("severity") != "info"
    ][:3]
    recommendations = [
        {
            "insight_id": insight["id"],
            "text": f"Consider reviewing this: {insight['title']}.",
        }
        for insight in actionable
    ]
    warnings = [
        insight["message"]
        for insight in insights
        if insight.get("severity") in {"warning", "critical"}
    ][:3]

    return {
        "overview": overview,
        "key_findings": [insight["message"] for insight in insights[:5]],
        "budget_analysis": budget_analysis,
        "category_analysis": category_analysis,
        "recommendations": recommendations,
        "warnings": warnings,
    }


_CHAT_LEAK_PATTERNS = (
    "system prompt",
    "internal instructions",
    "tool schema",
    "api key",
    "model configuration",
    "developer message",
)


def _collect_chat_text(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _collect_chat_text(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _collect_chat_text(item)


def _allowed_chat_numbers(tool_results, facts, prefs):
    allowed = set(_iter_numbers(tool_results))
    allowed.update(_iter_numbers(facts))
    for text in _collect_chat_text(tool_results):
        for match in MONEY_CLAIM.finditer(text):
            value = _parse_number(match.group(1), prefs)
            if value is not None:
                allowed.add(value)
        for match in PERCENT_CLAIM.finditer(text):
            value = _parse_number(match.group(1), prefs)
            if value is not None:
                allowed.add(value)
    return allowed


def validate_chat_answer(answer, question, facts, tool_results, scope_ok=True, refusal=REFUSAL):
    payload = answer if isinstance(answer, dict) else None
    if payload is None:
        return ["Chat answer must be a JSON object."]
    try:
        parsed = ChatAnswer.model_validate(payload).model_dump()
    except ValidationError:
        return ["Chat answer failed the response schema."]

    errors = []
    text = parsed["answer"]
    lowered = text.lower()

    if not scope_ok and refusal.lower() not in lowered:
        errors.append("Out-of-scope questions must use the predefined refusal.")
    if scope_ok and BANNED_ADVICE.search(text):
        errors.append("Chat answer includes advice outside recorded spending data.")
    if any(pattern in lowered for pattern in _CHAT_LEAK_PATTERNS):
        errors.append("Chat answer discloses internal configuration.")
    if scope_ok and not any(phrase in lowered for phrase in CAUTIOUS_PHRASES):
        errors.append("Chat answer must use cautious language.")

    prefs = {
        "number_format": facts.get("formats", {}).get("number_format", "1,234.56")
    }
    allowed = _allowed_chat_numbers(tool_results, facts, prefs)
    for match in MONEY_CLAIM.finditer(text):
        value = _parse_number(match.group(1), prefs)
        if not _is_allowed(value, allowed):
            errors.append("Chat answer contains money not found in the tool results.")
    for match in PERCENT_CLAIM.finditer(text):
        value = _parse_number(match.group(1), prefs)
        if not _is_allowed(value, allowed, tolerance=0.1):
            errors.append("Chat answer contains a percentage not found in the tool results.")

    for suggestion in parsed["follow_up_suggestions"]:
        if len(suggestion) > 120:
            errors.append("Follow-up suggestions must be short.")
            break

    return list(dict.fromkeys(errors))


def build_chat_fallback(question, facts, tool_results, scope_ok=True, intent=None, refusal=REFUSAL):
    if not scope_ok or not tool_results:
        return {"answer": refusal, "follow_up_suggestions": []}

    period = facts.get("period", {}).get("label", "this period")
    income = facts.get("income", {}).get("display", "no income")
    expenses = facts.get("expenses", {}).get("display_total", "no spending")
    budget_status = facts.get("budget", {}).get("status", "no_budget")

    answer = (
        f"Based on your data for {period}, you recorded {income} of income and "
        f"{expenses} of spending. Your overall budget status is {budget_status}. "
        "I can break any of those figures down further."
    )
    return {
        "answer": answer,
        "follow_up_suggestions": follow_up_suggestions(intent),
    }
