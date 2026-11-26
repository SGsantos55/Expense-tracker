"""Financial period resolution, financial-month buckets and proration helpers."""
import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ai.config import AI_MAX_PERIOD_DAYS
from ai.formatting import format_period_label

PRESETS = ("this_week", "this_month", "last_month", "custom", "ytd")


class PeriodError(ValueError):
    """Raised when a requested period is invalid."""


@dataclass(frozen=True)
class Period:
    preset: str
    start: date
    end: date
    budget_basis: str
    income_basis: str
    comparison_start: date
    comparison_end: date
    label: str
    comparison_label: str

    def to_dict(self):
        return {
            "preset": self.preset,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "budget_basis": self.budget_basis,
            "income_basis": self.income_basis,
            "comparison_start": self.comparison_start.isoformat(),
            "comparison_end": self.comparison_end.isoformat(),
            "label": self.label,
            "comparison_label": self.comparison_label,
        }


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError as exc:
            raise PeriodError("Dates must use YYYY-MM-DD format.") from exc
    raise PeriodError("A valid date is required.")


def _start_day(prefs):
    try:
        return max(1, min(28, int((prefs or {}).get("financial_month_start_day", 1))))
    except (TypeError, ValueError):
        return 1


def financial_month_range(today, start_day):
    """Return (start_date, end_date) for the financial month containing today."""
    today = _as_date(today)
    start_day = max(1, min(28, int(start_day)))
    if today.day >= start_day:
        start = today.replace(day=start_day)
    else:
        first_of_this_month = today.replace(day=1)
        prev_month_end = first_of_this_month - timedelta(days=1)
        start = prev_month_end.replace(day=min(start_day, prev_month_end.day))

    if start.month == 12:
        next_month_start = start.replace(year=start.year + 1, month=1)
    else:
        next_month_start = start.replace(month=start.month + 1)
    end = next_month_start - timedelta(days=1)
    return start, end


def overlap_days(start_a, end_a, start_b, end_b):
    start = max(start_a, start_b)
    end = min(end_a, end_b)
    if start > end:
        return 0
    return (end - start).days + 1


def financial_month_buckets(start, end, start_day):
    buckets = []
    cursor = start
    while cursor <= end:
        bucket_start, bucket_end = financial_month_range(cursor, start_day)
        overlap = overlap_days(start, end, bucket_start, bucket_end)
        if overlap:
            buckets.append({
                "start": bucket_start,
                "end": bucket_end,
                "days": (bucket_end - bucket_start).days + 1,
                "overlap_days": overlap,
            })
        cursor = bucket_end + timedelta(days=1)
    return buckets


def calendar_month_buckets(start, end):
    buckets = []
    cursor = start.replace(day=1)
    while cursor <= end:
        days_in_month = calendar.monthrange(cursor.year, cursor.month)[1]
        month_start = cursor
        month_end = cursor.replace(day=days_in_month)
        overlap = overlap_days(start, end, month_start, month_end)
        if overlap:
            buckets.append({
                "start": month_start,
                "end": month_end,
                "days": days_in_month,
                "overlap_days": overlap,
            })
        if cursor.month == 12:
            cursor = cursor.replace(year=cursor.year + 1, month=1)
        else:
            cursor = cursor.replace(month=cursor.month + 1)
    return buckets


def _is_full_financial_month(start, end, start_day):
    month_start, month_end = financial_month_range(start, start_day)
    return start == month_start and end == month_end


def _is_full_calendar_month(start, end):
    if start.year != end.year or start.month != end.month or start.day != 1:
        return False
    return end.day == calendar.monthrange(start.year, start.month)[1]


def _previous_year_range(start, end):
    prev_start = start.replace(year=start.year - 1)
    try:
        prev_end = end.replace(year=end.year - 1)
    except ValueError:
        prev_end = end.replace(year=end.year - 1, day=28)
    return prev_start, prev_end


def _comparison_range(preset, start, end, start_day):
    if preset == "this_week":
        comparison_end = start - timedelta(days=1)
        comparison_start = comparison_end - timedelta(days=6)
    elif preset in {"this_month", "last_month"}:
        comparison_start, comparison_end = financial_month_range(
            start - timedelta(days=1), start_day
        )
    elif preset == "custom":
        length = (end - start).days
        comparison_end = start - timedelta(days=1)
        comparison_start = comparison_end - timedelta(days=length)
    else:
        comparison_start, comparison_end = _previous_year_range(start, end)
    return comparison_start, comparison_end


def resolve_period(preset="this_month", date_from=None, date_to=None, prefs=None, today=None):
    """Resolve a preset into a validated Period with a comparison range."""
    prefs = prefs or {}
    start_day = _start_day(prefs)
    if today is None:
        today = date.today()
    today = _as_date(today)
    preset = (preset or "this_month").strip().lower()

    if preset not in PRESETS:
        raise PeriodError("Unknown period preset.")

    if preset == "this_week":
        start = today - timedelta(days=today.weekday())
        end = today
    elif preset == "this_month":
        start, end = financial_month_range(today, start_day)
    elif preset == "last_month":
        current_start, _ = financial_month_range(today, start_day)
        start, end = financial_month_range(current_start - timedelta(days=1), start_day)
    elif preset == "custom":
        if not date_from or not date_to:
            raise PeriodError("Custom periods require both a start and end date.")
        start = _as_date(date_from)
        end = _as_date(date_to)
        if start > end:
            raise PeriodError("Start date must be before end date.")
        if end > today:
            raise PeriodError("End date cannot be in the future.")
        if (end - start).days + 1 > AI_MAX_PERIOD_DAYS:
            raise PeriodError(f"Periods cannot exceed {AI_MAX_PERIOD_DAYS} days.")
    else:
        start = date(today.year, 1, 1)
        end = today

    comparison_start, comparison_end = _comparison_range(preset, start, end, start_day)
    budget_basis = (
        "full_month"
        if _is_full_financial_month(start, end, start_day)
        else "prorated"
    )
    income_basis = (
        "full_month"
        if _is_full_calendar_month(start, end)
        else "prorated"
    )

    return Period(
        preset=preset,
        start=start,
        end=end,
        budget_basis=budget_basis,
        income_basis=income_basis,
        comparison_start=comparison_start,
        comparison_end=comparison_end,
        label=format_period_label(start, end, prefs),
        comparison_label=format_period_label(comparison_start, comparison_end, prefs),
    )
