"""Preference-aware formatting shared by the app and the AI layer."""
import calendar
from datetime import date, datetime

CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "INR": "₹",
    "NPR": "Rs",
    "AUD": "A$",
    "CAD": "C$",
}

NUMBER_FORMATS = {
    "1,234.56": (",", "."),
    "1.234,56": (".", ","),
    "1 234.56": (" ", "."),
}

DATE_FORMATS = {
    "YYYY-MM-DD": "%Y-%m-%d",
    "DD/MM/YYYY": "%d/%m/%Y",
    "MM/DD/YYYY": "%m/%d/%Y",
}

DEFAULT_PREFS = {
    "preferred_currency": "NPR",
    "financial_month_start_day": 1,
    "number_format": "1,234.56",
    "date_format": "YYYY-MM-DD",
}


def currency_symbol(code):
    return CURRENCY_SYMBOLS.get(code, code)


def format_number(value, prefs=None, decimals=2):
    prefs = prefs or {}
    thousands, decimal = NUMBER_FORMATS.get(
        prefs.get("number_format", "1,234.56"), (",", ".")
    )
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    formatted = f"{number:,.{decimals}f}"
    if (thousands, decimal) != (",", "."):
        formatted = (
            formatted.replace(",", "\x00")
            .replace(".", decimal)
            .replace("\x00", thousands)
        )
    return formatted


def format_money(value, prefs=None, decimals=2):
    prefs = prefs or {}
    code = prefs.get("preferred_currency", "NPR")
    return f"{currency_symbol(code)} {format_number(value, prefs, decimals)}"


def format_date(value, prefs=None):
    prefs = prefs or {}
    fmt = DATE_FORMATS.get(
        prefs.get("date_format", "YYYY-MM-DD"), "%Y-%m-%d"
    )
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.strptime(value[:10], "%Y-%m-%d")
        except ValueError:
            return value
    return value.strftime(fmt)


def format_month(value, prefs=None):
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.strptime(value[:7], "%Y-%m")
        except ValueError:
            return value
    return value.strftime("%B %Y")


def format_percent(value, decimals=1):
    if value is None:
        return ""
    return f"{float(value):.{decimals}f}%"


def _as_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def format_period_label(start, end, prefs=None):
    start_date = _as_date(start)
    end_date = _as_date(end)
    if not start_date or not end_date:
        return ""
    if (
        start_date.day == 1
        and start_date.year == end_date.year
        and start_date.month == end_date.month
        and end_date.day == calendar.monthrange(start_date.year, start_date.month)[1]
    ):
        return format_month(start_date, prefs)
    return f"{format_date(start_date, prefs)} – {format_date(end_date, prefs)}"
