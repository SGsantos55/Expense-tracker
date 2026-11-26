"""Read-only, user-scoped tools available to the chat workflow."""
import re

from ai.formatting import format_money
from database.db import get_db

TOOL_NAMES = (
    "get_income_summary",
    "get_expense_summary",
    "get_budget_status",
    "get_category_breakdown",
    "compare_periods",
    "search_transactions",
    "get_financial_insights",
    "what_if_reduce_category",
)

TOOLS_FOR_INTENT = {
    "overview": (),
    "income": ("get_income_summary",),
    "expenses": ("get_expense_summary",),
    "budget": ("get_budget_status",),
    "category": ("get_category_breakdown",),
    "comparison": ("compare_periods",),
    "search": ("search_transactions",),
    "insights": ("get_financial_insights",),
    "what_if": ("what_if_reduce_category",),
}

_AMOUNT = re.compile(r"\d+(?:[.,]\d+)?")
_PERCENT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


def _normalise(value):
    return " ".join(str(value or "").lower().split())


def _amount(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _category_from_message(message, facts):
    text = _normalise(message)
    rows = facts.get("expenses", {}).get("by_category") or []
    for row in rows:
        name = _normalise(row.get("name"))
        if name and len(name) > 2 and name in text:
            return row["name"]
    return None


def build_tool_args(intent, message, facts):
    args = {}
    if intent in {"search", "what_if"}:
        category = _category_from_message(message, facts)
        if category:
            args["category"] = category
    if intent == "search":
        text = _normalise(message)
        above = re.search(r"(?:above|over|more than)\s+(" + _AMOUNT.pattern + r")", text)
        below = re.search(r"(?:below|under|less than)\s+(" + _AMOUNT.pattern + r")", text)
        if above:
            args["min_amount"] = _amount(above.group(1))
        if below:
            args["max_amount"] = _amount(below.group(1))
        args["limit"] = 10
    if intent == "what_if":
        match = _PERCENT.search(str(message or ""))
        args["percent"] = _amount(match.group(1)) if match else 10
    return {key: value for key, value in args.items() if value is not None}


def _search_transactions(user_id, period, facts, args):
    clauses = ["user_id = %s", "date BETWEEN %s AND %s"]
    params = [user_id, period.start.isoformat(), period.end.isoformat()]

    requested_category = args.get("category")
    categories = {
        _normalise(row.get("name")): row["name"]
        for row in facts.get("expenses", {}).get("by_category") or []
    }
    category = categories.get(_normalise(requested_category))
    if category:
        clauses.append("LOWER(category) = LOWER(%s)")
        params.append(category)

    text = str(args.get("text") or "")[:100].strip()
    if text:
        clauses.append("LOWER(COALESCE(description, '')) LIKE LOWER(%s)")
        params.append(f"%{text}%")

    for column, key, operator in (
        ("amount", "min_amount", ">="),
        ("amount", "max_amount", "<="),
    ):
        value = _amount(args.get(key))
        if value is not None:
            clauses.append(f"{column} {operator} %s")
            params.append(value)

    try:
        limit = max(1, min(20, int(args.get("limit", 10))))
    except (TypeError, ValueError):
        limit = 10
    params.append(limit)

    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT date, category, amount, description
            FROM expenses
            WHERE """
            + " AND ".join(clauses)
            + " ORDER BY date DESC, id DESC LIMIT %s",
            params,
        ).fetchall()
    finally:
        conn.close()

    prefs = facts.get("prefs") or {}
    return [
        {
            "date": row["date"],
            "category": row["category"],
            "amount": row["amount"],
            "display": format_money(row["amount"], prefs),
            "description": row["description"] or "",
        }
        for row in rows
    ]


def _what_if(args, facts):
    rows = facts.get("expenses", {}).get("by_category") or []
    if not rows:
        return {"available": False, "message": "No spending was recorded in this period."}
    requested = _normalise(args.get("category"))
    row = next(
        (item for item in rows if _normalise(item.get("name")) == requested),
        rows[0],
    )
    try:
        percent = max(1, min(100, float(args.get("percent", 10))))
    except (TypeError, ValueError):
        percent = 10
    current = float(row.get("amount") or 0)
    reduction = current * percent / 100
    prefs = facts.get("prefs") or {}
    return {
        "available": True,
        "category": row["name"],
        "percent": percent,
        "current_spend": current,
        "display_current": format_money(current, prefs),
        "projected_reduction": reduction,
        "display_reduction": format_money(reduction, prefs),
        "projected_spend": current - reduction,
        "display_projected": format_money(current - reduction, prefs),
        "period": facts.get("period", {}).get("label", ""),
    }


def execute_tool(name, args, user_id, period, facts):
    if name not in TOOL_NAMES:
        raise ValueError(f"Unknown tool: {name}")

    if name == "get_income_summary":
        return facts.get("income", {})
    if name == "get_expense_summary":
        return facts.get("expenses", {})
    if name == "get_budget_status":
        return facts.get("budget", {})
    if name == "get_category_breakdown":
        return facts.get("expenses", {}).get("by_category", [])
    if name == "compare_periods":
        return {
            "current": facts.get("expenses", {}).get("total"),
            "previous": facts.get("expenses", {}).get("previous_total"),
            "delta_amount": facts.get("expenses", {}).get("delta_amount"),
            "delta_pct": facts.get("expenses", {}).get("delta_pct"),
            "delta_label": facts.get("expenses", {}).get("delta_label"),
            "income_delta_label": facts.get("income", {}).get("delta_label"),
            "comparison_label": facts.get("period", {}).get("comparison_label"),
        }
    if name == "search_transactions":
        return _search_transactions(user_id, period, facts, args)
    if name == "get_financial_insights":
        return facts.get("insights", [])
    return _what_if(args, facts)
