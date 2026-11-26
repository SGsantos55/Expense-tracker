"""Deterministic financial facts for the summary and chat workflows."""
import calendar
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from ai.config import BUDGET_WARNING_THRESHOLD
from ai.formatting import currency_symbol, format_money
from ai.insights import detect_insights
from ai.periods import financial_month_buckets, overlap_days
from database.db import get_db
from database.settings_queries import get_user_preferences

MONEY = Decimal("0.01")
ZERO = Decimal("0")


def _dec(value):
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _money(value):
    if value is None:
        return None
    return float(_dec(value).quantize(MONEY, rounding=ROUND_HALF_UP))


def _pct(numerator, denominator):
    if denominator is None or _dec(denominator) == 0:
        return None
    return round(float(_dec(numerator) / _dec(denominator) * 100), 1)


def _delta_label(current, previous):
    if _dec(previous) == 0:
        return "new" if _dec(current) > 0 else "0.0%"
    return f"{_pct(_dec(current) - _dec(previous), previous):.1f}%"


def _parse_month(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:7], "%Y-%m").date().replace(day=1)
    except ValueError:
        return None


def _fetch_expenses(conn, user_id, start, end):
    rows = conn.execute(
        "SELECT id, amount, category, date FROM expenses "
        "WHERE user_id = %s AND date BETWEEN %s AND %s "
        "ORDER BY date, id",
        (user_id, start.isoformat(), end.isoformat()),
    ).fetchall()
    return [dict(row) for row in rows]


def load_source_data(user_id, period):
    conn = get_db()
    try:
        month_from = min(period.start, period.comparison_start).strftime("%Y-%m")
        month_to = max(period.end, period.comparison_end).strftime("%Y-%m")
        return {
            "expenses": _fetch_expenses(conn, user_id, period.start, period.end),
            "previous_expenses": _fetch_expenses(
                conn, user_id, period.comparison_start, period.comparison_end
            ),
            "income_entries": [
                dict(row) for row in conn.execute(
                    "SELECT id, source, amount, effective_month FROM income_entries "
                    "WHERE user_id = %s AND effective_month BETWEEN %s AND %s "
                    "ORDER BY effective_month, id",
                    (user_id, month_from, month_to),
                ).fetchall()
            ],
            "budgets": [
                dict(row) for row in conn.execute(
                    "SELECT id, category_id, monthly_limit FROM budgets "
                    "WHERE user_id = %s",
                    (user_id,),
                ).fetchall()
            ],
            "categories": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "color": row["color"],
                    "is_archived": bool(row["is_archived"]),
                }
                for row in conn.execute(
                    "SELECT id, name, color, is_archived FROM categories "
                    "WHERE user_id = %s AND type = 'expense' ORDER BY name",
                    (user_id,),
                ).fetchall()
            ],
        }
    finally:
        conn.close()


def _sum_by_category(rows):
    totals = {}
    for row in rows:
        name = row.get("category") or "Uncategorized"
        totals[name] = totals.get(name, ZERO) + _dec(row.get("amount"))
    return totals


def _allocate_income(entries, start, end):
    total = ZERO
    count = 0
    for entry in entries:
        month_start = _parse_month(entry.get("effective_month"))
        if month_start is None:
            continue
        days_in_month = calendar.monthrange(month_start.year, month_start.month)[1]
        month_end = month_start.replace(day=days_in_month)
        days = overlap_days(start, end, month_start, month_end)
        if not days:
            continue
        total += _dec(entry.get("amount")) * Decimal(days) / Decimal(days_in_month)
        count += 1
    return total, count


def _prorate_budget(limit, start, end, start_day):
    if limit is None:
        return None
    total = ZERO
    for bucket in financial_month_buckets(start, end, start_day):
        total += _dec(limit) * Decimal(bucket["overlap_days"]) / Decimal(bucket["days"])
    return _money(total)


def _budget_status(spent, allowance):
    if allowance is None or _dec(allowance) <= 0:
        return "no_budget"
    utilisation = float(_dec(spent) / _dec(allowance) * 100)
    if utilisation >= 100:
        return "over"
    if utilisation >= BUDGET_WARNING_THRESHOLD:
        return "near_limit"
    return "ok"


def _money_display(value, prefs):
    if value is None:
        return ""
    return format_money(value, prefs)


def calculate_facts(period, prefs, expenses, previous_expenses, income_entries, budgets, categories):
    prefs = prefs or {}
    start_day = int(prefs.get("financial_month_start_day", 1) or 1)
    currency_code = prefs.get("preferred_currency", "NPR")

    total = sum((_dec(row.get("amount")) for row in expenses), ZERO)
    previous_total = sum((_dec(row.get("amount")) for row in previous_expenses), ZERO)
    by_category = _sum_by_category(expenses)
    previous_by_category = _sum_by_category(previous_expenses)

    daily = {}
    for row in expenses:
        day = str(row.get("date") or "")[:10]
        if day:
            daily[day] = daily.get(day, ZERO) + _dec(row.get("amount"))

    income_total, income_count = _allocate_income(income_entries, period.start, period.end)
    previous_income, previous_income_count = _allocate_income(
        income_entries, period.comparison_start, period.comparison_end
    )

    budget_limits = {}
    for row in budgets:
        budget_limits[row["category_id"]] = _dec(row["monthly_limit"])

    overall_limit = budget_limits.get(None)
    overall_allowance = _prorate_budget(overall_limit, period.start, period.end, start_day)
    overall_remaining = (
        _money(_dec(overall_allowance) - total) if overall_allowance is not None else None
    )

    category_lookup = {category["name"]: category for category in categories}
    category_names = set(category_lookup)
    candidate_names = set(by_category) | set(previous_by_category)
    for category in categories:
        name = category["name"]
        has_budget = category["id"] in budget_limits
        has_activity = name in by_category or name in previous_by_category
        if not category["is_archived"] or has_budget or has_activity:
            candidate_names.add(name)

    category_rows = []
    for name in candidate_names:
        category = category_lookup.get(name)
        category_id = category["id"] if category else None
        limit = budget_limits.get(category_id) if category_id is not None else None
        allowance = _prorate_budget(limit, period.start, period.end, start_day)
        spent = by_category.get(name, ZERO)
        previous_spent = previous_by_category.get(name, ZERO)
        remaining = _money(_dec(allowance) - spent) if allowance is not None else None
        delta_amount = _money(spent - previous_spent)
        row = {
            "name": name,
            "category_id": category_id,
            "color": category["color"] if category else None,
            "is_archived": bool(category["is_archived"]) if category else False,
            "is_known": category is not None,
            "budgeted": limit is not None,
            "limit": _money(limit),
            "allowance": allowance,
            "spent": _money(spent),
            "previous_spent": _money(previous_spent),
            "remaining": remaining,
            "utilisation": _pct(spent, allowance),
            "share": _pct(spent, total),
            "status": _budget_status(spent, allowance),
            "delta_amount": delta_amount,
            "delta_pct": _pct(spent - previous_spent, previous_spent),
            "delta_label": _delta_label(spent, previous_spent),
            "display_limit": _money_display(_money(limit), prefs),
            "display_allowance": _money_display(allowance, prefs),
            "display_spent": _money_display(_money(spent), prefs),
            "display_remaining": _money_display(remaining, prefs),
        }
        category_rows.append(row)

    category_rows.sort(key=lambda row: (-row["spent"], row["name"]))

    uncategorized = sum(
        (amount for name, amount in by_category.items() if name not in category_names),
        ZERO,
    )
    top_name = max(by_category, key=by_category.get) if by_category else None
    top_amount = by_category.get(top_name, ZERO) if top_name else ZERO

    has_budget = any(limit is not None for limit in budget_limits.values())
    has_income = income_count > 0
    has_expenses = bool(expenses)
    has_categories = bool(categories)

    income_facts = {
        "amount": _money(income_total),
        "display": _money_display(_money(income_total), prefs),
        "basis": period.income_basis,
        "entry_count": income_count,
        "previous_amount": _money(previous_income),
        "previous_entry_count": previous_income_count,
        "delta_amount": _money(income_total - previous_income),
        "delta_pct": _pct(income_total - previous_income, previous_income),
        "delta_label": _delta_label(income_total, previous_income),
    }

    expenses_facts = {
        "total": _money(total),
        "display_total": _money_display(_money(total), prefs),
        "count": len(expenses),
        "by_category": [
            {
                "name": name,
                "amount": _money(amount),
                "display": _money_display(_money(amount), prefs),
                "share": _pct(amount, total),
                "previous_amount": _money(previous_by_category.get(name, ZERO)),
            }
            for name, amount in sorted(
                by_category.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "top_category": top_name,
        "top_category_amount": _money(top_amount),
        "top_category_share": _pct(top_amount, total),
        "daily": [
            {"date": day, "amount": _money(amount)}
            for day, amount in sorted(daily.items())
        ],
        "previous_total": _money(previous_total),
        "delta_amount": _money(total - previous_total),
        "delta_pct": _pct(total - previous_total, previous_total),
        "delta_label": _delta_label(total, previous_total),
    }

    budget_facts = {
        "limit": _money(overall_limit),
        "display_limit": _money_display(_money(overall_limit), prefs),
        "allowance": overall_allowance,
        "display_allowance": _money_display(overall_allowance, prefs),
        "spent": _money(total),
        "display_spent": _money_display(_money(total), prefs),
        "remaining": overall_remaining,
        "display_remaining": _money_display(overall_remaining, prefs),
        "utilisation": _pct(total, overall_allowance),
        "status": _budget_status(total, overall_allowance),
        "basis": period.budget_basis,
        "categories": category_rows,
    }

    comparison_facts = {
        "period": {
            "start": period.comparison_start.isoformat(),
            "end": period.comparison_end.isoformat(),
            "label": period.comparison_label,
        },
        "expenses_total": _money(previous_total),
        "expenses_delta": _money(total - previous_total),
        "expenses_delta_pct": _pct(total - previous_total, previous_total),
        "expenses_delta_label": _delta_label(total, previous_total),
        "income_amount": _money(previous_income),
        "income_delta": _money(income_total - previous_income),
        "income_delta_pct": _pct(income_total - previous_income, previous_income),
        "income_delta_label": _delta_label(income_total, previous_income),
    }

    return {
        "period": period.to_dict(),
        "currency": {
            "code": currency_code,
            "symbol": currency_symbol(currency_code),
        },
        "formats": {
            "number_format": prefs.get("number_format", "1,234.56"),
            "date_format": prefs.get("date_format", "YYYY-MM-DD"),
        },
        "income": income_facts,
        "expenses": expenses_facts,
        "budget": budget_facts,
        "comparison": comparison_facts,
        "savings": {
            "amount": _money(income_total - total),
            "display": _money_display(_money(income_total - total), prefs),
            "status": "surplus" if income_total >= total else "deficit",
        },
        "data_quality": {
            "has_expenses": has_expenses,
            "has_income": has_income,
            "has_budget": has_budget,
            "has_categories": has_categories,
            "uncategorized_spend": _money(uncategorized),
        },
    }


def build_facts(user_id, period, prefs=None):
    if prefs is None:
        prefs = get_user_preferences(user_id) or {}
    source = load_source_data(user_id, period)
    facts = calculate_facts(
        period,
        prefs,
        source["expenses"],
        source["previous_expenses"],
        source["income_entries"],
        source["budgets"],
        source["categories"],
    )
    facts["insights"] = detect_insights(facts)
    return facts
