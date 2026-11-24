# Spec: Profile & Financial Settings

## Overview
This feature adds a dedicated Settings area where a logged-in user configures
how their money is tracked across the rest of the app: custom expense/income
categories, their monthly income history, overall and per-category budgets,
and display preferences (currency, financial-month start day, date/number
formats, default export format). It builds on the existing profile/dashboard
and expense features by replacing the hardcoded `VALID_CATEGORIES` list and
absent budget/income concepts with real, user-owned, persisted data, laying
the groundwork for budget warnings and richer reporting in later steps.

## Depends on
- 02-registration.md and 03-login-logout.md (a logged-in user/session is required)
- 05-backend-route-profile-page.md (the profile page and `g.user_id` session pattern)
- 07-add-expense.md (existing `VALID_CATEGORIES` / custom-category sentinel pattern
  that category management replaces)

## Routes
- `GET /settings` — settings hub showing categories, income, budgets, preferences — logged-in
- `GET/POST /settings/categories` — list + create a category — logged-in
- `POST /settings/categories/<int:id>/edit` — rename, re-icon, or recolor a category — logged-in
- `POST /settings/categories/<int:id>/archive` — archive/unarchive a category (soft delete) — logged-in
- `POST /settings/categories/<int:id>/delete` — permanently delete a category not in use — logged-in
- `GET/POST /settings/income` — view income history + add a new income entry — logged-in
- `POST /settings/income/<int:id>/delete` — remove an income history entry — logged-in
- `GET/POST /settings/budgets` — view/set overall monthly budget and per-category budgets — logged-in
- `GET/POST /settings/preferences` — view/update currency, financial-month start day,
  date/number format, default export format — logged-in

All routes redirect to `/login` if `g.user_id` is not set, following the
existing pattern used in `profile()` and `add_expense()`.

## Database changes
Verified against `database/db.py` — none of the following tables/columns exist yet.

New tables (added to `init_db()` via `CREATE TABLE IF NOT EXISTS`, plus a
migration in `_run_migrations()` for the new `users` columns):

```sql
CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('expense', 'income')),
    icon TEXT,
    color TEXT,
    is_archived SMALLINT NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (now()::text),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE (user_id, name, type)
);

CREATE TABLE IF NOT EXISTS income_entries (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    source TEXT NOT NULL,          -- e.g. 'Salary', 'Freelancing', 'Business'
    amount DOUBLE PRECISION NOT NULL,
    effective_month TEXT NOT NULL, -- 'YYYY-MM', first day of the effective month
    created_at TEXT NOT NULL DEFAULT (now()::text),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS budgets (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL,
    category_id INTEGER,            -- NULL = overall monthly budget
    monthly_limit DOUBLE PRECISION NOT NULL,
    created_at TEXT NOT NULL DEFAULT (now()::text),
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (category_id) REFERENCES categories(id),
    UNIQUE (user_id, category_id)
);
```

New columns on `users` (migrations, each `ADD COLUMN IF NOT EXISTS`):
- `preferred_currency TEXT NOT NULL DEFAULT 'USD'`
- `financial_month_start_day SMALLINT NOT NULL DEFAULT 1`
- `date_format TEXT NOT NULL DEFAULT 'YYYY-MM-DD'`
- `number_format TEXT NOT NULL DEFAULT '1,234.56'`
- `default_export_format TEXT NOT NULL DEFAULT 'xlsx'`

`expenses.category` stays a `TEXT` column for backward compatibility; new
expenses from users who have defined categories store the category `name`
(not a foreign key) so existing rows and the `VALID_CATEGORIES` fallback
keep working unchanged.

## Templates
- **Create:**
  - `templates/settings/index.html` — settings hub with links to each section
  - `templates/settings/categories.html` — category list, add/edit/archive/delete forms
  - `templates/settings/income.html` — income history table + add-income form
  - `templates/settings/budgets.html` — overall + per-category budget form with
    consumed/remaining progress bars
  - `templates/settings/preferences.html` — currency/date/number/export format form
- **Modify:**
  - `templates/base.html` — add a "Settings" link to the logged-in nav
  - `templates/profile.html` — add a link/card into Settings
  - `templates/expenses/add_expense.html` and `templates/expenses/edit_expense.html` —
    populate the category `<select>` from the user's active categories instead of
    (or in addition to) the hardcoded `VALID_CATEGORIES`

## Files to change
- `app.py` — add the new routes above, extend `inject_categories()` to pull
  user-defined categories, update `resolve_category`/`validate_expense_form`
  if user categories replace the hardcoded list
- `database/db.py` — add the three new tables and the five new `users` columns
  in `init_db()` / `_run_migrations()`
- `database/queries.py` — add query functions (see below)
- `templates/base.html`, `templates/profile.html` — add navigation links
- `templates/expenses/add_expense.html`, `templates/expenses/edit_expense.html` —
  source categories from the database

## Files to create
- `database/settings_queries.py` (or additional functions in `database/queries.py`) —
  `get_categories(user_id, type=None, include_archived=False)`,
  `create_category(...)`, `update_category(...)`, `archive_category(...)`,
  `delete_category(...)`, `get_income_entries(user_id)`, `add_income_entry(...)`,
  `delete_income_entry(...)`, `get_budgets(user_id)`, `set_budget(...)`,
  `get_budget_consumption(user_id, month)`, `get_user_preferences(user_id)`,
  `update_user_preferences(user_id, ...)`
- `templates/settings/index.html`
- `templates/settings/categories.html`
- `templates/settings/income.html`
- `templates/settings/budgets.html`
- `templates/settings/preferences.html`
- `tests/test_settings.py` — route and query tests for the above

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Every new route must check `g.user_id` and redirect to `/login` if absent,
  matching the existing pattern in `profile()`
- Every query must scope rows by `user_id` so one user can never read or
  modify another user's categories, income, budgets, or preferences
- Category names are validated with the same pattern/length rules already
  used for custom categories in `app.py` (`CUSTOM_CATEGORY_PATTERN`,
  `CUSTOM_CATEGORY_MAX_LENGTH`)
- A category in use by at least one expense cannot be hard-deleted — only
  archived; archived categories are excluded from the add/edit expense
  `<select>` but still render correctly on historical expenses

## Definition of done
- [ ] Logged-in user can visit `/settings` and see links to Categories,
      Income, Budgets, and Preferences
- [ ] User can add a custom expense category and a custom income category,
      each with a name, icon, and color, and see them listed separately by type
- [ ] User can edit a category's name/icon/color and the change is reflected
      immediately in the category list
- [ ] User can archive a category; it disappears from the add-expense category
      dropdown but still shows correctly on past expenses using it
- [ ] User can permanently delete a category that has no expenses linked to it;
      attempting to delete a category in use shows an error instead
- [ ] User can set a monthly income amount with an effective month and see it
      appear in an income history list ordered by most recent first
- [ ] User can add a second income entry for a different source (e.g.
      Freelancing) in the same month and both appear in the history
- [ ] User can set an overall monthly budget and see how much of it has been
      consumed based on real expense totals for the current financial month
- [ ] User can set a budget for a specific category and see a warning when
      consumption is at or above a threshold (e.g. 90%) of that budget
- [ ] User can change preferred currency, financial-month start day, date
      format, number format, and default export format, and the values persist
      across logins
- [ ] All new routes redirect anonymous visitors to `/login`
- [ ] `pytest` passes, including new tests in `tests/test_settings.py`
