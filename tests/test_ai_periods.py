from datetime import date

import pytest

from ai.periods import (
    PeriodError,
    calendar_month_buckets,
    financial_month_buckets,
    financial_month_range,
    overlap_days,
    resolve_period,
)

TODAY = date(2026, 6, 15)
PREFS = {
    "preferred_currency": "NPR",
    "financial_month_start_day": 25,
    "number_format": "1,234.56",
    "date_format": "YYYY-MM-DD",
}


def test_financial_month_range_for_day_25():
    start, end = financial_month_range(TODAY, 25)
    assert start == date(2026, 5, 25)
    assert end == date(2026, 6, 24)


def test_financial_month_range_rolls_back_before_start_day():
    start, end = financial_month_range(date(2026, 6, 10), 25)
    assert start == date(2026, 5, 25)
    assert end == date(2026, 6, 24)


def test_this_month_uses_financial_month():
    period = resolve_period("this_month", prefs=PREFS, today=TODAY)
    assert period.start == date(2026, 5, 25)
    assert period.end == date(2026, 6, 24)
    assert period.budget_basis == "full_month"
    assert period.income_basis == "prorated"
    assert period.comparison_start == date(2026, 4, 25)
    assert period.comparison_end == date(2026, 5, 24)


def test_this_month_with_start_day_one_is_full_calendar_month():
    prefs = dict(PREFS, financial_month_start_day=1)
    period = resolve_period("this_month", prefs=prefs, today=TODAY)
    assert period.start == date(2026, 6, 1)
    assert period.end == date(2026, 6, 30)
    assert period.budget_basis == "full_month"
    assert period.income_basis == "full_month"


def test_last_month_is_previous_complete_financial_month():
    period = resolve_period("last_month", prefs=PREFS, today=TODAY)
    assert period.start == date(2026, 4, 25)
    assert period.end == date(2026, 5, 24)
    assert period.comparison_start == date(2026, 3, 25)
    assert period.comparison_end == date(2026, 4, 24)
    assert period.budget_basis == "full_month"
    assert period.income_basis == "prorated"


def test_this_week_starts_on_monday():
    period = resolve_period("this_week", prefs=PREFS, today=TODAY)
    assert period.start == date(2026, 6, 15)
    assert period.end == TODAY
    assert period.comparison_end == date(2026, 6, 14)
    assert period.comparison_start == date(2026, 6, 8)
    assert period.budget_basis == "prorated"
    assert period.income_basis == "prorated"


def test_custom_period_is_inclusive():
    period = resolve_period(
        "custom", "2026-06-01", "2026-06-15", prefs=PREFS, today=TODAY
    )
    assert period.start == date(2026, 6, 1)
    assert period.end == date(2026, 6, 15)
    assert period.comparison_start == date(2026, 5, 17)
    assert period.comparison_end == date(2026, 5, 31)
    assert period.budget_basis == "prorated"
    assert period.income_basis == "prorated"


def test_custom_full_calendar_month_has_month_basis():
    period = resolve_period(
        "custom", "2026-05-01", "2026-05-31", prefs=PREFS, today=TODAY
    )
    assert period.income_basis == "full_month"
    assert period.budget_basis == "prorated"
    assert period.label == "May 2026"


def test_custom_period_validation():
    with pytest.raises(PeriodError, match="both a start and end"):
        resolve_period("custom", prefs=PREFS, today=TODAY)
    with pytest.raises(PeriodError, match="before end"):
        resolve_period("custom", "2026-06-10", "2026-06-01", prefs=PREFS, today=TODAY)
    with pytest.raises(PeriodError, match="future"):
        resolve_period("custom", "2026-06-01", "2026-06-16", prefs=PREFS, today=TODAY)
    with pytest.raises(PeriodError, match="cannot exceed"):
        resolve_period("custom", "2025-01-01", "2026-06-15", prefs=PREFS, today=TODAY)


def test_ytd_and_previous_year_comparison():
    period = resolve_period("ytd", prefs=PREFS, today=TODAY)
    assert period.start == date(2026, 1, 1)
    assert period.end == TODAY
    assert period.comparison_start == date(2025, 1, 1)
    assert period.comparison_end == date(2025, 6, 15)
    assert period.budget_basis == "prorated"
    assert period.income_basis == "prorated"


def test_ytd_leap_day_comparison_clamps():
    period = resolve_period("ytd", prefs=PREFS, today=date(2024, 2, 29))
    assert period.comparison_start == date(2023, 1, 1)
    assert period.comparison_end == date(2023, 2, 28)


def test_unknown_preset():
    with pytest.raises(PeriodError, match="Unknown period"):
        resolve_period("next_year", prefs=PREFS, today=TODAY)


def test_financial_month_buckets_cover_each_day_once():
    start = date(2026, 1, 1)
    end = date(2026, 6, 15)
    buckets = financial_month_buckets(start, end, 25)
    assert len(buckets) == 6
    assert sum(bucket["overlap_days"] for bucket in buckets) == (end - start).days + 1
    assert buckets[0]["start"] == date(2025, 12, 25)
    assert buckets[-1]["end"] == date(2026, 6, 24)


def test_calendar_month_buckets_cover_partial_months():
    start = date(2026, 1, 1)
    end = date(2026, 3, 15)
    buckets = calendar_month_buckets(start, end)
    assert [bucket["overlap_days"] for bucket in buckets] == [31, 28, 15]
    assert [bucket["days"] for bucket in buckets] == [31, 28, 31]


def test_overlap_days():
    assert overlap_days(
        date(2026, 6, 1), date(2026, 6, 10),
        date(2026, 6, 5), date(2026, 6, 15),
    ) == 6
    assert overlap_days(
        date(2026, 6, 1), date(2026, 6, 10),
        date(2026, 6, 11), date(2026, 6, 15),
    ) == 0


def test_period_to_dict_serialises_dates():
    period = resolve_period("this_month", prefs=PREFS, today=TODAY)
    data = period.to_dict()
    assert data["start"] == "2026-05-25"
    assert data["end"] == "2026-06-24"
    assert data["comparison_start"] == "2026-04-25"
    assert data["label"]
