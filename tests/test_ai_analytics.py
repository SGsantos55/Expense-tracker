from datetime import date

import pytest

from ai.analytics import build_facts, calculate_facts
from ai.formatting import format_date, format_money, format_number
from ai.insights import detect_insights
from ai.periods import resolve_period
from database.db import get_db
from database.settings_queries import seed_default_categories

TODAY = date(2026, 6, 15)
PREFS = {
    "preferred_currency": "NPR",
    "financial_month_start_day": 25,
    "number_format": "1,234.56",
    "date_format": "YYYY-MM-DD",
}


@pytest.fixture()
def golden_user():
    conn = get_db()
    try:
        row = conn.execute(
            "INSERT INTO users (name, email, email_verified) "
            "VALUES (%s, %s, 1) RETURNING id",
            ("AI Analytics Test", "ai-analytics@example.com"),
        ).fetchone()
        user_id = row["id"]
        conn.commit()
    finally:
        conn.close()

    seed_default_categories(user_id)

    conn = get_db()
    try:
        categories = {
            row["name"]: row["id"]
            for row in conn.execute(
                "SELECT id, name FROM categories "
                "WHERE user_id = %s AND type = 'expense'",
                (user_id,),
            ).fetchall()
        }
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO budgets (user_id, category_id, monthly_limit) "
                "VALUES (%s, %s, %s)",
                [
                    (user_id, None, 30000),
                    (user_id, categories["Food"], 10000),
                    (user_id, categories["Transport"], 5000),
                    (user_id, categories["Bills"], 8000),
                ],
            )
            cur.executemany(
                "INSERT INTO income_entries (user_id, source, amount, effective_month) "
                "VALUES (%s, %s, %s, %s)",
                [
                    (user_id, "Salary", 28000, "2026-04"),
                    (user_id, "Salary", 30000, "2026-05"),
                    (user_id, "Salary", 35000, "2026-06"),
                ],
            )
            cur.executemany(
                "INSERT INTO expenses (user_id, amount, category, date, description) "
                "VALUES (%s, %s, %s, %s, %s)",
                [
                    (user_id, 1500, "Food", "2026-05-20", "Previous food"),
                    (user_id, 500, "Transport", "2026-05-24", "Previous bus"),
                    (user_id, 3000, "Food", "2026-05-26", "Groceries"),
                    (user_id, 1500, "Transport", "2026-05-28", "Fuel"),
                    (user_id, 4000, "Bills", "2026-06-01", "Internet"),
                    (user_id, 2500, "Food", "2026-06-05", "Dinner"),
                    (user_id, 1200, "Shopping", "2026-06-10", "Headphones"),
                    (user_id, 800, "Transport", "2026-06-12", "Bus"),
                    (user_id, 1000, "Food", "2026-06-15", "Lunch"),
                ],
            )
        conn.commit()
    finally:
        conn.close()

    return {"id": user_id, "categories": categories}


def _category(facts, name):
    return next(row for row in facts["budget"]["categories"] if row["name"] == name)


def test_current_financial_month_facts(golden_user):
    period = resolve_period("this_month", prefs=PREFS, today=TODAY)
    facts = build_facts(golden_user["id"], period, PREFS)

    assert facts["period"]["start"] == "2026-05-25"
    assert facts["period"]["end"] == "2026-06-24"
    assert facts["period"]["budget_basis"] == "full_month"
    assert facts["period"]["income_basis"] == "prorated"

    assert facts["expenses"]["total"] == pytest.approx(14000.0)
    assert facts["expenses"]["count"] == 7
    assert facts["expenses"]["top_category"] == "Food"
    assert facts["expenses"]["top_category_amount"] == pytest.approx(6500.0)
    assert facts["expenses"]["top_category_share"] == pytest.approx(46.4)
    assert facts["expenses"]["previous_total"] == pytest.approx(2000.0)
    assert facts["expenses"]["delta_amount"] == pytest.approx(12000.0)
    assert facts["expenses"]["delta_pct"] == pytest.approx(600.0)

    assert facts["budget"]["limit"] == pytest.approx(30000.0)
    assert facts["budget"]["allowance"] == pytest.approx(30000.0)
    assert facts["budget"]["spent"] == pytest.approx(14000.0)
    assert facts["budget"]["remaining"] == pytest.approx(16000.0)
    assert facts["budget"]["utilisation"] == pytest.approx(46.7)
    assert facts["budget"]["status"] == "ok"

    food = _category(facts, "Food")
    assert food["limit"] == pytest.approx(10000.0)
    assert food["allowance"] == pytest.approx(10000.0)
    assert food["spent"] == pytest.approx(6500.0)
    assert food["remaining"] == pytest.approx(3500.0)
    assert food["utilisation"] == pytest.approx(65.0)
    assert food["status"] == "ok"
    assert food["delta_amount"] == pytest.approx(5000.0)
    assert food["delta_pct"] == pytest.approx(333.3)
    assert food["delta_label"] == "333.3%"

    transport = _category(facts, "Transport")
    assert transport["spent"] == pytest.approx(2300.0)
    assert transport["previous_spent"] == pytest.approx(500.0)
    assert transport["delta_amount"] == pytest.approx(1800.0)
    assert transport["delta_pct"] == pytest.approx(360.0)

    bills = _category(facts, "Bills")
    assert bills["delta_label"] == "new"

    shopping = _category(facts, "Shopping")
    assert shopping["budgeted"] is False
    assert shopping["status"] == "no_budget"

    assert facts["income"]["amount"] == pytest.approx(34774.19)
    assert facts["income"]["basis"] == "prorated"
    assert facts["income"]["entry_count"] == 2
    assert facts["income"]["previous_amount"] == pytest.approx(28825.81)
    assert facts["income"]["delta_pct"] == pytest.approx(20.6)

    assert facts["comparison"]["period"]["start"] == "2026-04-25"
    assert facts["comparison"]["period"]["end"] == "2026-05-24"
    assert facts["comparison"]["expenses_total"] == pytest.approx(2000.0)

    assert facts["data_quality"] == {
        "has_expenses": True,
        "has_income": True,
        "has_budget": True,
        "has_categories": True,
        "uncategorized_spend": 0.0,
    }


def test_custom_period_prorates_budget_and_income(golden_user):
    period = resolve_period(
        "custom", "2026-06-01", "2026-06-15", prefs=PREFS, today=TODAY
    )
    facts = build_facts(golden_user["id"], period, PREFS)

    assert facts["budget"]["allowance"] == pytest.approx(14516.13)
    assert facts["budget"]["spent"] == pytest.approx(9500.0)
    assert facts["budget"]["remaining"] == pytest.approx(5016.13)
    assert facts["budget"]["status"] == "ok"
    assert facts["expenses"]["count"] == 5
    assert facts["expenses"]["total"] == pytest.approx(9500.0)

    food = _category(facts, "Food")
    assert food["allowance"] == pytest.approx(4838.71)
    assert food["spent"] == pytest.approx(3500.0)
    assert food["remaining"] == pytest.approx(1338.71)
    assert food["status"] == "ok"

    assert facts["income"]["amount"] == pytest.approx(17500.0)
    assert facts["income"]["basis"] == "prorated"
    assert facts["comparison"]["expenses_total"] == pytest.approx(6500.0)


def test_this_week_prorates_one_day_of_budget(golden_user):
    period = resolve_period("this_week", prefs=PREFS, today=TODAY)
    facts = build_facts(golden_user["id"], period, PREFS)

    assert period.start == date(2026, 6, 15)
    assert facts["expenses"]["total"] == pytest.approx(1000.0)
    assert facts["budget"]["allowance"] == pytest.approx(967.74)
    assert facts["budget"]["remaining"] == pytest.approx(-32.26)
    assert facts["budget"]["status"] == "over"
    assert facts["income"]["amount"] == pytest.approx(1166.67)

    food = _category(facts, "Food")
    assert food["allowance"] == pytest.approx(322.58)
    assert food["spent"] == pytest.approx(1000.0)
    assert food["status"] == "over"


def test_last_month_is_full_financial_month(golden_user):
    period = resolve_period("last_month", prefs=PREFS, today=TODAY)
    facts = build_facts(golden_user["id"], period, PREFS)

    assert facts["expenses"]["total"] == pytest.approx(2000.0)
    assert facts["budget"]["allowance"] == pytest.approx(30000.0)
    assert facts["budget"]["remaining"] == pytest.approx(28000.0)
    assert facts["income"]["amount"] == pytest.approx(28825.81)


def test_custom_calendar_month_uses_full_income_but_prorated_budget(golden_user):
    period = resolve_period(
        "custom", "2026-05-01", "2026-05-31", prefs=PREFS, today=TODAY
    )
    facts = build_facts(golden_user["id"], period, PREFS)

    assert facts["period"]["income_basis"] == "full_month"
    assert facts["period"]["budget_basis"] == "prorated"
    assert facts["income"]["amount"] == pytest.approx(30000.0)
    assert facts["expenses"]["total"] == pytest.approx(6500.0)
    assert facts["budget"]["allowance"] == pytest.approx(30774.19)
    assert facts["budget"]["remaining"] == pytest.approx(24274.19)


def test_ytd_facts(golden_user):
    period = resolve_period("ytd", prefs=PREFS, today=TODAY)
    facts = build_facts(golden_user["id"], period, PREFS)

    assert facts["period"]["start"] == "2026-01-01"
    assert facts["period"]["end"] == "2026-06-15"
    assert facts["expenses"]["total"] == pytest.approx(16000.0)
    assert facts["budget"]["allowance"] == pytest.approx(164516.13)
    assert facts["budget"]["status"] == "ok"
    assert facts["income"]["amount"] == pytest.approx(75500.0)
    assert facts["comparison"]["expenses_total"] == pytest.approx(0.0)


def test_empty_facts_and_missing_data_insights():
    period = resolve_period(
        "custom", "2026-06-01", "2026-06-15", prefs=PREFS, today=TODAY
    )
    facts = calculate_facts(period, PREFS, [], [], [], [], [])
    ids = {insight["id"] for insight in detect_insights(facts)}

    assert facts["expenses"]["total"] == 0.0
    assert facts["expenses"]["top_category"] is None
    assert facts["budget"]["status"] == "no_budget"
    assert facts["budget"]["remaining"] is None
    assert facts["data_quality"]["has_expenses"] is False
    assert {"no_budget", "no_income", "no_expenses"} <= ids


def test_detect_insights_for_current_month(golden_user):
    period = resolve_period("this_month", prefs=PREFS, today=TODAY)
    facts = build_facts(golden_user["id"], period, PREFS)
    insights = facts["insights"]
    ids = {insight["id"] for insight in insights}

    assert "largest_category" in ids
    assert "category_up:Food" in ids
    assert "savings_surplus" in ids
    assert "income_up" in ids
    assert "unbudgeted:Shopping" in ids
    assert "overall_over_budget" not in ids
    assert "no_budget" not in ids

    largest = next(insight for insight in insights if insight["id"] == "largest_category")
    assert largest["severity"] == "info"
    assert largest["metrics"]["category"] == "Food"


def test_detect_over_budget_insights_for_week(golden_user):
    period = resolve_period("this_week", prefs=PREFS, today=TODAY)
    facts = build_facts(golden_user["id"], period, PREFS)
    ids = {insight["id"] for insight in facts["insights"]}

    assert "overall_over_budget" in ids
    assert "category_over:Food" in ids
    assert "category_over:Transport" not in ids


def test_formatting_helpers():
    assert format_number(1234.5, {"number_format": "1,234.56"}) == "1,234.50"
    assert format_number(1234.5, {"number_format": "1.234,56"}) == "1.234,50"
    assert format_number(1234.5, {"number_format": "1 234.56"}) == "1 234.50"
    assert format_number("not-a-number", {}) == "not-a-number"

    assert format_money(
        1234.5, {"preferred_currency": "NPR", "number_format": "1,234.56"}
    ) == "Rs 1,234.50"
    assert format_money(
        1234.5, {"preferred_currency": "USD", "number_format": "1.234,56"}
    ) == "$ 1.234,50"
    assert format_money(
        1234.5, {"preferred_currency": "EUR", "number_format": "1 234.56"}
    ) == "€ 1 234.50"

    assert format_date("2026-06-15", {"date_format": "DD/MM/YYYY"}) == "15/06/2026"
    assert format_date("2026-06-15", {"date_format": "MM/DD/YYYY"}) == "06/15/2026"
