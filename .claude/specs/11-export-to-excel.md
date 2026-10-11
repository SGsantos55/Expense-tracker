# Spec: Export to Excel

## Overview
This feature lets a logged-in user download their expenses as a formatted
Excel (`.xlsx`) workbook. It builds on the profile page and its date filter so
users can export either their full history or a specific date range for
offline record-keeping, sharing, or reporting. At this stage of the Spendly
roadmap the core CRUD and filtering flows are complete, so a native
spreadsheet export is the natural next step for giving users ownership of their
data.

## Depends on
- Step 03 — Login/Logout (authentication + `g.user_id`)
- Step 05 — Backend route for profile page (query helpers)
- Step 06 — Date filter on profile (reuses `date_from` / `date_to`)
- Step 07 — Add Expense (expense data to export)

## Routes
- `GET /expenses/export` — streams an `.xlsx` file of the current user's
  expenses, honouring optional `date_from` and `date_to` query parameters —
  logged-in only. Unauthenticated requests redirect to `/login`.

## Database changes
No database changes. Export reads existing `expenses` rows via a new read-only
query helper.

## Templates
- **Create:** none
- **Modify:** `templates/profile.html` — add an "Export to Excel" button/link
  in the transactions/header area that points to `/expenses/export`, carrying
  the active `date_from` / `date_to` values as query parameters so the export
  matches the currently filtered view.

## Files to change
- `app.py` — add the `/expenses/export` route, validating date params the same
  way as `profile`, and returning a Flask `Response` with the generated
  workbook bytes and the correct `Content-Type` /
  `Content-Disposition: attachment` headers.
- `database/queries.py` — add `get_expenses_for_export(user_id, date_from=None,
  date_to=None)` returning all matching expenses (not limited), newest first,
  with `date`, `category`, `description`, `amount`.
- `requirements.txt` — add the `openpyxl` dependency.

## Files to create
- `database/excel.py` — a small helper (no Flask imports) exposing
  `build_expense_workbook(rows)` that returns the workbook as `bytes`
  (via `io.BytesIO`) with a header row, one row per expense, and a total row.

## New dependencies
- `openpyxl` — pure-Python `.xlsx` generation (pin the installed version in
  `requirements.txt`).

## Rules for implementation
- No SQLAlchemy or ORMs — use `sqlite3` via `get_db()`.
- Parameterised queries only — never string-format user input into SQL.
- Passwords hashed with werkzeug (unchanged; no auth changes here).
- Use CSS variables — never hardcode hex values (for the profile button).
- All templates extend `base.html`.
- The export route must enforce ownership: only the logged-in user's expenses,
  scoped by `user_id`.
- Reuse the existing date-validation logic from `profile` (same
  `YYYY-MM-DD` parsing and `from <= to` check); invalid dates fall back to
  exporting all expenses.
- Keep Excel generation in `database/excel.py` free of Flask imports so it is
  unit-testable in isolation.
- Set `Content-Disposition` with a sensible filename, e.g.
  `expenses_<YYYY-MM-DD>.xlsx`, and the
  `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` MIME type.

## Definition of done
- `pip install -r requirements.txt` installs `openpyxl` without error.
- Visiting `/expenses/export` while logged out redirects to `/login`.
- Visiting `/expenses/export` while logged in downloads an `.xlsx` file that
  opens in Excel/LibreOffice and contains a header row, every one of the
  user's expenses, and a total row.
- Passing `?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` exports only expenses
  within that range; invalid/reversed dates export all expenses.
- The exported workbook never contains another user's expenses.
- The profile page shows an "Export to Excel" button that downloads the file
  and preserves the currently applied date filter.
- `pytest` passes.
