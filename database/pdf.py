"""PDF financial statement generation for expense exports — no Flask imports."""
import io
from datetime import date as date_obj
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

ACCENT = colors.HexColor("#1A472A")
ACCENT_LIGHT = colors.HexColor("#E8F0EB")
INK = colors.HexColor("#0F0F0F")
MUTED = colors.HexColor("#6B6B6B")
RULE = colors.HexColor("#E4E1DA")


def _money(value):
    return f"{(value or 0.0):,.2f}"


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 10 * mm, "Expense Tracker — Statement")
    canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_expense_pdf(rows, summary, categories, date_from, date_to, user_name):
    """Build a PDF financial statement and return it as bytes.

    Args:
        rows (list[dict]): Expenses (newest first) with date, category,
            description, amount.
        summary (dict): total_spent, transaction_count, top_category.
        categories (list[dict]): Category breakdown with name, amount, pct.
        date_from (str|None): Start of range (YYYY-MM-DD) or None.
        date_to (str|None): End of range (YYYY-MM-DD) or None.
        user_name (str): Name shown on the statement.

    Returns:
        bytes: The generated PDF.
    """
    base = getSampleStyleSheet()
    brand = ParagraphStyle("brand", parent=base["Title"], fontName="Helvetica-Bold",
                           fontSize=22, textColor=ACCENT, alignment=0, spaceAfter=2)
    title = ParagraphStyle("title", parent=base["Heading2"], fontName="Helvetica",
                           fontSize=13, textColor=INK, spaceAfter=2)
    meta = ParagraphStyle("meta", parent=base["Normal"], fontSize=9, textColor=MUTED)
    section = ParagraphStyle("section", parent=base["Heading3"], fontName="Helvetica-Bold",
                             fontSize=11, textColor=ACCENT, spaceBefore=14, spaceAfter=6)
    cell = ParagraphStyle("cell", parent=base["Normal"], fontSize=8.5, leading=10.5)

    if date_from and date_to:
        period = f"{date_from} to {date_to}"
    else:
        period = "All Time"

    story = [
        Paragraph("Expense Tracker", brand),
        Paragraph("Expense Statement", title),
        Paragraph(
            f"Prepared for {escape(user_name or '')} &nbsp;•&nbsp; Period: {period} "
            f"&nbsp;•&nbsp; Generated {date_obj.today().strftime('%Y-%m-%d')}", meta),
        Spacer(1, 6),
    ]

    story.append(Paragraph("Summary", section))
    summary_tbl = Table(
        [["Total spent", _money(summary.get("total_spent"))],
         ["Transactions", str(summary.get("transaction_count", 0))],
         ["Top category", escape(str(summary.get("top_category", "—")))]],
        colWidths=[50 * mm, 60 * mm], hAlign="LEFT")
    summary_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
        ("BACKGROUND", (0, 0), (-1, -1), ACCENT_LIGHT),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(summary_tbl)

    story.append(Paragraph("Category Breakdown", section))
    cat_data = [["Category", "Share", "Amount"]]
    for c in categories:
        cat_data.append([c["name"], f"{c['pct']}%", _money(c["amount"])])
    if len(cat_data) == 1:
        cat_data.append(["No expenses", "", ""])
    cat_tbl = Table(cat_data, colWidths=[80 * mm, 30 * mm, 40 * mm], hAlign="LEFT",
                    repeatRows=1)
    cat_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 1, ACCENT),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, RULE),
    ]))
    story.append(cat_tbl)

    story.append(Paragraph("Detailed Expenses", section))
    # Running total accumulates oldest -> newest.
    chronological = list(reversed(rows))
    running = 0.0
    body = []
    for r in chronological:
        running += r["amount"] or 0.0
        body.append([
            str(r["date"]),
            Paragraph(escape(r["category"] or ""), cell),
            Paragraph(escape(r["description"] or ""), cell),
            _money(r["amount"]),
            _money(running),
        ])
    data = [["Date", "Category", "Description", "Amount", "Running Total"]] + body
    if not body:
        data.append(["", "No expenses in this period", "", "", ""])
    else:
        data.append(["", "", "Total", _money(running), ""])

    tbl = Table(data, colWidths=[24 * mm, 32 * mm, 64 * mm, 25 * mm, 29 * mm],
                repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if body:
        style += [
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEABOVE", (0, -1), (-1, -1), 1, ACCENT),
            ("BACKGROUND", (0, -1), (-1, -1), ACCENT_LIGHT),
        ]
    tbl.setStyle(TableStyle(style))
    story.append(tbl)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=22 * mm, title="Expense Tracker Expense Statement")
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
