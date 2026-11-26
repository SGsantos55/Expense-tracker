"""Rule-based financial insights derived from deterministic facts."""
from ai.formatting import format_money, format_percent

CATEGORY_INCREASE_PCT = 15.0
CATEGORY_INCREASE_ABS = 100.0
UNBUDGETED_MIN_SPEND = 100.0
LARGEST_CATEGORY_MIN_SHARE = 25.0
INCOME_CHANGE_MIN_PCT = 10.0


def _prefs(facts):
    return {
        "preferred_currency": facts["currency"]["code"],
        "number_format": facts["formats"]["number_format"],
        "date_format": facts["formats"]["date_format"],
    }


def _money(facts, value):
    return format_money(value, _prefs(facts))


def _pct(value):
    return format_percent(value)


def _insight(insight_id, severity, kind, title, message, metrics=None):
    return {
        "id": insight_id,
        "severity": severity,
        "kind": kind,
        "title": title,
        "message": message,
        "metrics": metrics or {},
    }


def detect_insights(facts):
    insights = []
    budget = facts["budget"]
    expenses = facts["expenses"]
    income = facts["income"]
    quality = facts["data_quality"]

    if budget["status"] == "over":
        insights.append(_insight(
            "overall_over_budget",
            "critical",
            "budget",
            "Overall budget exceeded",
            (
                f"You have spent {_money(facts, budget['spent'])} against an allowance of "
                f"{_money(facts, budget['allowance'])} ({_pct(budget['utilisation'])})."
            ),
            {
                "spent": budget["spent"],
                "allowance": budget["allowance"],
                "utilisation": budget["utilisation"],
            },
        ))
    elif budget["status"] == "near_limit":
        insights.append(_insight(
            "overall_near_limit",
            "warning",
            "budget",
            "Overall budget nearly used",
            (
                f"You have used {_pct(budget['utilisation'])} of your overall budget "
                f"({_money(facts, budget['remaining'])} remaining)."
            ),
            {
                "spent": budget["spent"],
                "allowance": budget["allowance"],
                "remaining": budget["remaining"],
                "utilisation": budget["utilisation"],
            },
        ))

    for row in budget["categories"]:
        if row["status"] == "over":
            insights.append(_insight(
                f"category_over:{row['name']}",
                "critical",
                "category",
                f"{row['name']} is over budget",
                (
                    f"{row['name']} spending is {_money(facts, row['spent'])} against an "
                    f"allowance of {_money(facts, row['allowance'])} "
                    f"({_pct(row['utilisation'])})."
                ),
                {
                    "category": row["name"],
                    "spent": row["spent"],
                    "allowance": row["allowance"],
                    "utilisation": row["utilisation"],
                },
            ))
        elif row["status"] == "near_limit":
            insights.append(_insight(
                f"category_near:{row['name']}",
                "warning",
                "category",
                f"{row['name']} is nearing its limit",
                (
                    f"{row['name']} spending is {_pct(row['utilisation'])} of its "
                    f"allowance ({_money(facts, row['remaining'])} remaining)."
                ),
                {
                    "category": row["name"],
                    "spent": row["spent"],
                    "allowance": row["allowance"],
                    "remaining": row["remaining"],
                    "utilisation": row["utilisation"],
                },
            ))

        if (
            row["delta_pct"] is not None
            and row["delta_pct"] >= CATEGORY_INCREASE_PCT
            and row["delta_amount"] >= CATEGORY_INCREASE_ABS
            and row["status"] != "over"
        ):
            insights.append(_insight(
                f"category_up:{row['name']}",
                "warning",
                "trend",
                f"{row['name']} spending increased",
                (
                    f"{row['name']} spending is up {_pct(row['delta_pct'])} "
                    f"({_money(facts, row['delta_amount'])}) compared with the previous period."
                ),
                {
                    "category": row["name"],
                    "current_spent": row["spent"],
                    "previous_spent": row["previous_spent"],
                    "delta_amount": row["delta_amount"],
                    "delta_pct": row["delta_pct"],
                },
            ))

    top_category = expenses["top_category"]
    if top_category and (expenses["top_category_share"] or 0) >= LARGEST_CATEGORY_MIN_SHARE:
        insights.append(_insight(
            "largest_category",
            "info",
            "category",
            "Largest spending category",
            (
                f"{top_category} is your largest category at "
                f"{_money(facts, expenses['top_category_amount'])} "
                f"({_pct(expenses['top_category_share'])} of spending)."
            ),
            {
                "category": top_category,
                "amount": expenses["top_category_amount"],
                "share": expenses["top_category_share"],
            },
        ))

    if (
        income["previous_amount"] > 0
        and income["amount"] > 0
        and income["delta_pct"] is not None
        and abs(income["delta_pct"]) >= INCOME_CHANGE_MIN_PCT
    ):
        direction = "increased" if income["delta_pct"] > 0 else "decreased"
        insights.append(_insight(
            f"income_{'up' if income['delta_pct'] > 0 else 'down'}",
            "info",
            "income",
            f"Income {direction}",
            (
                f"Income is {direction} by {_pct(abs(income['delta_pct']))} compared "
                f"with the previous period."
            ),
            {
                "current_income": income["amount"],
                "previous_income": income["previous_amount"],
                "delta_pct": income["delta_pct"],
            },
        ))

    if income["entry_count"] > 0:
        savings = income["amount"] - expenses["total"]
        if savings < 0:
            insights.append(_insight(
                "savings_deficit",
                "critical",
                "savings",
                "Spending exceeds income",
                (
                    f"Expenses are {_money(facts, abs(savings))} higher than income "
                    "for this period."
                ),
                {"income": income["amount"], "expenses": expenses["total"], "savings": savings},
            ))
        else:
            insights.append(_insight(
                "savings_surplus",
                "info",
                "savings",
                "Income covers spending",
                (
                    f"Income exceeds expenses by {_money(facts, savings)} for this period."
                ),
                {"income": income["amount"], "expenses": expenses["total"], "savings": savings},
            ))

    for row in budget["categories"]:
        if (
            row["limit"] is None
            and row["spent"] >= UNBUDGETED_MIN_SPEND
        ):
            insights.append(_insight(
                f"unbudgeted:{row['name']}",
                "warning",
                "budget",
                f"{row['name']} has no budget",
                (
                    f"{row['name']} has {_money(facts, row['spent'])} of spending but "
                    "no category budget."
                ),
                {"category": row["name"], "spent": row["spent"]},
            ))

    if not quality["has_budget"]:
        insights.append(_insight(
            "no_budget",
            "info",
            "budget",
            "No budget set",
            "No overall or category budget is set for this period.",
        ))
    if not quality["has_income"]:
        insights.append(_insight(
            "no_income",
            "info",
            "income",
            "No income recorded",
            "No income entries were found for this period.",
        ))
    if not quality["has_expenses"]:
        insights.append(_insight(
            "no_expenses",
            "info",
            "expenses",
            "No expenses recorded",
            "No expenses were recorded for this period.",
        ))

    return insights
