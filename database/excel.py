"""Excel workbook generation for expense exports — no Flask imports."""
import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

HEADERS = ["Date", "Category", "Description", "Amount"]
TEMPLATES = ("minimal", "professional", "analytics", "aesthetic")
DEFAULT_TEMPLATE = "minimal"

# Expense Tracker palette (RGB hex, no leading #)
INK = "0F0F0F"
ACCENT = "1A472A"
ACCENT_LIGHT = "E8F0EB"
GOLD = "C17F24"
GOLD_LIGHT = "FDF3E3"
NEON = "00E58F"
NEON_LIGHT = "E6FBF0"
PAPER = "F7F6F3"
BORDER = "E4E1DA"
WHITE = "FFFFFF"

MONEY_FORMAT = '#,##0.00'


def _fill(color):
    return PatternFill("solid", start_color=color, end_color=color)


def _description(row):
    return row["description"] or row["category"]


def _amount(row):
    return row["amount"] or 0.0


def _write_rows(ws, rows, header_style, row_style=None, total_style=None,
                col_widths=(14, 20, 40, 14), money_format=False):
    ws.append(HEADERS)
    for cell in ws[1]:
        header_style(cell)

    total = 0.0
    for i, row in enumerate(rows):
        amount = _amount(row)
        total += amount
        ws.append([row["date"], row["category"], _description(row), amount])
        if row_style:
            for cell in ws[ws.max_row]:
                row_style(cell, i)
        if money_format:
            ws.cell(row=ws.max_row, column=4).number_format = MONEY_FORMAT

    total_idx = ws.max_row + 1
    ws.cell(row=total_idx, column=3, value="Total")
    ws.cell(row=total_idx, column=4, value=total)
    if money_format:
        ws.cell(row=total_idx, column=4).number_format = MONEY_FORMAT
    for col in (1, 2, 3, 4):
        cell = ws.cell(row=total_idx, column=col)
        if total_style:
            total_style(cell)
        else:
            cell.font = Font(bold=True)

    for letter, width in zip("ABCD", col_widths):
        ws.column_dimensions[letter].width = width
    return total


def _build_minimal(wb, rows):
    ws = wb.active
    ws.title = "Expenses"
    _write_rows(
        ws, rows,
        header_style=lambda c: setattr(c, "font", Font(bold=True)),
        col_widths=(14, 18, 36, 12),
    )


def _build_professional(wb, rows):
    ws = wb.active
    ws.title = "Expenses"
    thin = Side(style="thin", color=BORDER)
    box = Border(left=thin, right=thin, top=thin, bottom=thin)

    def header(c):
        c.font = Font(bold=True, color=WHITE, name="Calibri", size=11)
        c.fill = _fill(ACCENT)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = box

    def body(c, i):
        c.border = box
        c.font = Font(name="Calibri", size=10)
        if c.column == 4:
            c.alignment = Alignment(horizontal="right")

    def total(c):
        c.font = Font(bold=True, name="Calibri", size=11)
        c.fill = _fill(ACCENT_LIGHT)
        c.border = Border(top=Side(style="double", color=ACCENT), bottom=thin)
        if c.column == 4:
            c.alignment = Alignment(horizontal="right")

    _write_rows(ws, rows, header, body, total,
                col_widths=(14, 20, 44, 16), money_format=True)
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:D{ws.max_row - 1}"


def _build_analytics(wb, rows):
    ws = wb.active
    ws.title = "Expenses"

    def header(c):
        c.font = Font(bold=True, color=WHITE)
        c.fill = _fill(INK)
        c.alignment = Alignment(horizontal="center")

    def total(c):
        c.font = Font(bold=True)
        c.fill = _fill(PAPER)

    grand_total = _write_rows(ws, rows, header, None, total,
                              col_widths=(14, 20, 40, 14), money_format=True)
    ws.freeze_panes = "A2"

    summary = wb.create_sheet("Summary")
    summary.append(["Category", "Total", "Count", "Share"])
    for cell in summary[1]:
        header(cell)

    by_cat = {}
    for row in rows:
        entry = by_cat.setdefault(row["category"], [0.0, 0])
        entry[0] += _amount(row)
        entry[1] += 1
    for name, (amt, count) in sorted(by_cat.items(), key=lambda kv: -kv[1][0]):
        share = amt / grand_total if grand_total else 0.0
        summary.append([name, amt, count, share])
        r = summary.max_row
        summary.cell(row=r, column=2).number_format = MONEY_FORMAT
        summary.cell(row=r, column=4).number_format = "0.0%"

    t = summary.max_row + 1
    summary.cell(row=t, column=1, value="Total")
    summary.cell(row=t, column=2, value=grand_total).number_format = MONEY_FORMAT
    summary.cell(row=t, column=3, value=len(rows))
    summary.cell(row=t, column=4, value=1.0 if grand_total else 0.0).number_format = "0.0%"
    for col in range(1, 5):
        total(summary.cell(row=t, column=col))
    for letter, width in zip("ABCD", (24, 16, 10, 10)):
        summary.column_dimensions[letter].width = width


def _build_aesthetic(wb, rows):
    ws = wb.active
    ws.title = "Expenses"

    def header(c):
        c.font = Font(bold=True, color=ACCENT, name="Georgia", size=12)
        c.fill = _fill(NEON)
        c.alignment = Alignment(horizontal="center", vertical="center")

    def body(c, i):
        c.fill = _fill(NEON_LIGHT if i % 2 == 0 else GOLD_LIGHT)
        c.font = Font(name="Calibri", size=10, color=INK)
        if c.column == 4:
            c.alignment = Alignment(horizontal="right")

    def total(c):
        c.font = Font(bold=True, color=WHITE, name="Georgia", size=12)
        c.fill = _fill(ACCENT)
        if c.column == 4:
            c.alignment = Alignment(horizontal="right")

    _write_rows(ws, rows, header, body, total,
                col_widths=(14, 20, 42, 16), money_format=True)
    ws.row_dimensions[1].height = 26
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A2"


_BUILDERS = {
    "minimal": _build_minimal,
    "professional": _build_professional,
    "analytics": _build_analytics,
    "aesthetic": _build_aesthetic,
}


def build_expense_workbook(rows, template=DEFAULT_TEMPLATE):
    """Build an .xlsx workbook of expenses and return it as bytes.

    Args:
        rows (list[dict]): Expenses with date, category, description, amount.
        template (str): One of TEMPLATES; unknown values fall back to minimal.

    Returns:
        bytes: The generated .xlsx workbook.
    """
    builder = _BUILDERS.get(template, _build_minimal)
    wb = Workbook()
    builder(wb, rows)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
