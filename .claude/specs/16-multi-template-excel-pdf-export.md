# Spec: Multi-Template Excel Export + PDF Export

## Overview
This feature upgrades Expense Tracker's existing single-template Excel export (Step
11) into a polished export system. Logged-in users choose between an Excel
workbook (one of four visual templates: Minimal, Professional, Analytics,
Aesthetic) and a single polished PDF financial statement, both honouring the
currently applied profile date filter. At this stage of the roadmap, core
CRUD, filtering, and a basic Excel export already exist, so the natural next
step is giving users richer, presentation-ready exports of their own data
without introducing any new storage or auth concerns.

## Depends on
- Step 03 — Login/Logout (authentication + `g.user_id`)
- Step 05 — Backend route for profile page (query helpers)
- Step 06 — Date filter on profile (reuses `date_from` / `date_to`)
- Step 07 — Add Expense (expense data to export)
- Step 11 — Export to Excel (existing `/expenses/export` route,
  `database/excel.py`, `get_expenses_for_export`) — this spec replaces its
  single-template behaviour with a template-selectable one and keeps the
  route backward compatible.

## Routes
- `GET /expenses/export` — modified. Streams an `.xlsx` file of the current
  user's expenses, honouring optional `date_from` / `date_to` query
  parameters and a new optional `template` query parameter
  (`minimal` | `professional` | `analytics` | `aesthetic`, default
  `minimal`) — logged-in only. Unauthenticated requests redirect to
  `/login`. Invalid `template` values fall back to `minimal`.
- `GET /expenses/export/pdf` — new. Streams a `.pdf` financial statement of
  the current user's expenses, honouring the same `date_from` / `date_to`
  query parameters — logged-in only. Unauthenticated requests redirect to
  `/login`.

## Database changes
No database changes. Both exports read existing `expenses` rows via the
existing `get_expenses_for_export` read-only query helper; the PDF report
additionally reuses the existing `get_summary_stats` and
`get_category_breakdown` helpers for its summary and category sections. The
`expenses` table has no `title` column — "title" in each Excel template is
rendered from the existing `description` field (falling back to the
category name when the description is empty).

## Templates
- **Create:** none (export UI lives in a new section of `templates/profile.html`,
  styled via a new stylesheet — see Files to create).
- **Modify:** `templates/profile.html` — replace the single "Export to
  Excel" link with an "Export" trigger that opens a modal/panel offering:
  (1) a format choice (Excel / PDF) and (2) for Excel, four visual template
  cards (Minimal, Professional, Analytics, Aesthetic) with a short preview
  description of each, consistent with the existing `modal-overlay` pattern
  used in `templates/landing.html`. The chosen format/template is submitted
  as query parameters on the existing `date_from` / `date_to` filtered
  export links so the exported file matches the active filter.

## Files to change
- `app.py` — modify `export_expenses` to read a `template` query parameter,
  validate it against the four allowed values, and pass it to
  `build_expense_workbook`; add the new `export_expenses_pdf` route that
  validates dates the same way as `profile`/`export_expenses`, calls
  `get_expenses_for_export`, `get_summary_stats`, and
  `get_category_breakdown`, builds the PDF via `build_expense_pdf`, and
  returns a `Response` with `application/pdf` mimetype and
  `Content-Disposition: attachment`.
- `database/excel.py` — rename/extend `build_expense_workbook(rows,
  template="minimal")` to dispatch to four private builder functions
  (`_build_minimal`, `_build_professional`, `_build_analytics`,
  `_build_aesthetic`), each producing a distinct formatted workbook (column
  widths, header styling/fills, fonts, and — for Analytics — a totals-by-category
  summary sheet; for Aesthetic — accent-colored banding matching the
  Expense Tracker palette expressed as RGB hex constants local to this module).
- `templates/profile.html` — update the export section/markup as described
  above.
- `static/css/profile.css` — add styles for the export modal and template
  preview cards, using existing CSS variables only.
- `requirements.txt` — add the `reportlab` dependency (pin installed
  version).

## Files to create
- `database/pdf.py` — a small helper (no Flask imports) exposing
  `build_expense_pdf(rows, summary, categories, date_from, date_to,
  user_name)` that returns the PDF as `bytes` (via `io.BytesIO`), using
  `reportlab`. Layout: Expense Tracker branding/wordmark and report title at the
  top, the selected date range (or "All Time"), a summary section (total
  spent, transaction count, top category), a category breakdown table, and
  a detailed expenses table with a running total — styled as a financial
  statement (ruled lines, right-aligned amounts, page numbers/footer), not
  a plain data dump.
- `static/js/export.js` — small script controlling the export modal: open/
  close behaviour (mirroring the existing `landing.html` modal JS), format
  toggle (Excel vs PDF), template-card selection state, and building the
  final export URL (including `date_from`/`date_to`/`template`) before
  navigating to it.

## New dependencies
- `reportlab` — pure-Python PDF generation (pin the installed version in
  `requirements.txt`).

## Rules for implementation
- No SQLAlchemy or ORMs — use `psycopg` via `get_db()`.
- Parameterised queries only — never string-format user input into SQL.
- Passwords hashed with werkzeug (unchanged; no auth changes here).
- Use CSS variables — never hardcode hex values in templates/CSS; hex
  constants are only acceptable inside `database/excel.py` /
  `database/pdf.py` where they drive openpyxl/reportlab styling, not markup.
- All templates extend `base.html`.
- Both export routes must enforce ownership: only the logged-in user's
  expenses, scoped by `user_id`.
- Reuse the existing date-validation logic from `profile`/`export_expenses`
  (same `YYYY-MM-DD` parsing and `from <= to` check); invalid dates fall
  back to exporting all expenses.
- Keep `database/excel.py` and `database/pdf.py` free of Flask imports so
  they are unit-testable in isolation.
- Validate the `template` query parameter against an explicit allow-list;
  never pass unvalidated input into file generation logic.
- Set `Content-Disposition` with sensible filenames, e.g.
  `expenses_<template>_<YYYY-MM-DD>.xlsx` and
  `expenses_statement_<YYYY-MM-DD>.pdf`, and correct MIME types
  (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` and
  `application/pdf`).

## Definition of done
- `pip install -r requirements.txt` installs `reportlab` without error.
- Visiting `/expenses/export` or `/expenses/export/pdf` while logged out
  redirects to `/login`.
- `/expenses/export?template=minimal` downloads an `.xlsx` with header row,
  date/category/description/amount columns, proper column widths, and a
  total row.
- `/expenses/export?template=professional`, `?template=analytics`, and
  `?template=aesthetic` each download a visibly distinct, correctly
  formatted `.xlsx` (verified by opening in LibreOffice/Excel).
- An invalid or missing `template` value exports the Minimal template.
- `/expenses/export/pdf` downloads a `.pdf` containing Expense Tracker branding, the
  report title, the selected date range, a summary section, and a detailed
  expenses table styled as a financial statement.
- Passing `?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` on either route
  exports only expenses within that range; invalid/reversed dates export
  all expenses.
- Neither export ever contains another user's expenses.
- The profile page's Export control opens a modal/panel showing format
  options (Excel/PDF) and four Excel template preview cards, matches the
  existing Expense Tracker design system (fonts, spacing, CSS variables), and is
  responsive on mobile widths.
- Selecting a template and clicking export downloads the correct file while
  preserving the currently applied date filter.
- `pytest` passes.
