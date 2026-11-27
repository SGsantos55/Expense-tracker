# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Flask-based expense tracker web application called "Expense Tracker". It's a student project with placeholder routes for future implementation steps.

## Common Commands

```bash
# Run the development server
python app.py

# Run tests
pytest

# Run with specific test file
pytest -v test_file.py

# Activate virtual environment
source venv/bin/activate
```

The app runs on port 5001 with debug mode enabled (`app.run(debug=True, port=5001)`).

## Architecture

### Technology Stack
- **Framework**: Flask 3.1.3
- **Database**: PostgreSQL (via psycopg 3); connection string in `DATABASE_URL`
- **Testing**: pytest with pytest-flask
- **Templating**: Jinja2 (built into Flask)

### Directory Structure

```
expense-tracker/
├── app.py              # Main Flask application & routes
├── ai/                 # Financial intelligence (deterministic facts + cached LLM narrative)
│   ├── analytics.py    # Facts: totals, budgets, income, comparisons
│   ├── chat_policy.py  # Deterministic chat scope/intent rules and refusal
│   ├── config.py       # AI environment/config constants
│   ├── fingerprint.py  # Cache invalidation hash over facts/settings/prefs
│   ├── formatting.py   # Shared money/date/number formatting
│   ├── graphs/         # LangGraph summary and chat workflows
│   ├── insights.py     # Rule-based insight detection
│   ├── llm.py          # Only Groq-specific module
│   ├── periods.py      # Periods, presets, and proration
│   ├── prompts.py      # Versioned summary and chat prompts
│   ├── rate_limit.py   # Per-user summary/chat quotas
│   ├── schemas.py      # Pydantic summary/chat output schemas
│   ├── service.py      # Flask-facing page/summary/chat API
│   ├── tools.py        # Read-only user-scoped chat tools
│   └── validation.py   # Numeric grounding, scope checks, fallback narratives
├── database/
│   ├── ai_queries.py  # Summary cache, chat sessions, usage accounting, fingerprint stats
│   ├── db.py          # Schema creation and seed data
│   ├── queries.py     # Core data queries
│   └── settings_queries.py # Categories, budgets, income, preferences
├── templates/         # Jinja2 HTML templates
│   ├── base.html     # Base template with nav & footer
│   ├── insights/     # Insights page, summary partial, chat UI
│   ├── landing.html   # Homepage
│   ├── login.html     # Login page
│   ├── terms.html     # Terms & conditions
│   └── privacy.html   # Privacy policy
└── static/
    ├── css/style.css  # Main stylesheet
    ├── css/insights.css # Insights page styles
    ├── js/main.js     # Main JavaScript file
    └── js/insights.js # Period selector, summary loading, chat requests
```

### Route Structure (app.py)

- `/` - Landing page
- `/register` - Redirects to `/login` (no password registration)
- `/login` - Login (Google OAuth only; `/login/google`, `/login/google/callback`)
- `/terms` - Terms & conditions
- `/privacy` - Privacy policy
- `/about` - About Us page (public)
- `/contact` - Contact Us page (public form; submissions stored in `contact_messages`)
- `/admin/messages` - Admin-only list of contact submissions (single admin by email; 404 otherwise)
- `/logout` - Logout (placeholder)
- `/profile` - Profile
- `/insights` - Insights page with deterministic facts and cached summary (logged-in only)
- `/insights/summary` - Generate/regenerate cached summary (form-encoded, rate-limited)
- `/insights/chat` - Scoped chat answer (JSON POST, rate-limited, logged-in only)
- `/insights/chat/clear` - Clear the current user's chat session (JSON or form POST)
- `/expenses/add` - Add expense
- `/expenses/<int:id>/edit` - Edit expense (placeholder)
- `/expenses/<int:id>/delete` - Delete expense (placeholder)

### Database Module (database/db.py)

This module connects to **PostgreSQL** using **psycopg 3**:
- `get_db()` - Returns a psycopg connection with `dict_row` row factory
  (so rows support `row['column']` access), using the `DATABASE_URL`
  environment variable (defaults to `postgresql:///spendly`)
- `init_db()` - Creates tables with CREATE TABLE IF NOT EXISTS
- `seed_db()` - Inserts sample development data (no-op if users exist)

Configuration: set `DATABASE_URL` in `.env` (see `.env.example`). Local
development uses the Unix socket with peer auth
(`postgresql:///spendly`). Tests run against a separate `spendly_test`
database (see `tests/conftest.py`).

### AI Financial Intelligence (ai/)

Phase 1 deterministic analytics are complete. Phase 2/3 add the `/insights`
page and a cached Groq-generated narrative with deterministic fallback. Phase 4
adds scoped, tool-grounded chat with deterministic refusal and fallback.

- `ai/periods.py` - `resolve_period()` supports `this_week`, `this_month`,
  `last_month`, `custom`, and `ytd`, returning comparison ranges and
  budget/income basis.
- `ai/analytics.py` - `build_facts(user_id, period, prefs)` loads source data
  and returns expenses, category breakdowns, budget status, income, savings,
  comparison totals, insights, and data-quality flags. Money math uses
  `Decimal` and `ROUND_HALF_UP`.
- `ai/insights.py` - `detect_insights(facts)` returns stable rule-based
  insights (over budget, category increases, savings, missing data). Rules do
  not call an LLM.
- `ai/fingerprint.py` - Canonical SHA-256 cache key over preferences,
  categories, budgets, and expense/income data.
- `ai/chat_policy.py` - Deterministic keyword allowlist, prompt-injection
  refusal, and follow-up suggestions.
- `ai/graphs/summary_graph.py` - LangGraph workflow: resolve period, load
  context, compute facts, check cache, generate, validate/retry, fallback,
  persist.
- `ai/graphs/chat_graph.py` - LangGraph workflow: guard scope, resolve period,
  route tools, generate, validate/retry, fallback, persist messages.
- `ai/tools.py` - Read-only, user-scoped tools; transaction search is
  parameterized and capped at 20 rows.
- `ai/rate_limit.py` - Per-user summary/chat quotas backed by `ai_usage`.
- `ai/llm.py` - The only provider-specific module; wraps Groq via
  `langchain-groq` and parses structured JSON output.
- `ai/validation.py` - Schema, numeric grounding, recommendation linkage,
  advice/scope checks, and deterministic fallback narratives.
- `ai/service.py` - Flask-facing page, summary, and chat API.
- `ai/formatting.py` - Shared preference-aware formatting; `app.py` wraps these
  helpers with the current request's user preferences.
- `ai/config.py` - AI env/config constants, including `AI_ENABLED`,
  `AI_MODEL`, limits, and `BUDGET_WARNING_THRESHOLD`.

Rules:
- Python owns all numbers; the LLM may only explain validated facts.
- `GET /insights` never calls an LLM. Generation is form-encoded and
  rate-limited; cached summaries are reused unless `force=1`.
- Chat is JSON-only, same-origin checked, and fails closed on uncertain or
  out-of-scope questions with a predefined refusal.
- Groq imports stay confined to `ai/llm.py`; never send raw transaction rows
  in summary facts. Chat may send up to 20 matching transaction rows only for
  transaction-search questions.
- Budgets are prorated by financial-month day overlap; income by calendar-month
  day overlap. Full amounts are used when a period is exactly one month.
- AI env vars live in `.env` (see `.env.example`). `AI_ENABLED=false` and an
  empty `GROQ_API_KEY` are valid; the page still renders deterministic facts
  and a computed fallback summary.

## Key Implementation Details

- The base template uses DM Serif Display and DM Sans fonts from Google Fonts
- CSS uses CSS variables for theming (e.g., `--neon-green`)
- The brand icon is ◈ (diamond character)
- Database connection is configured via `DATABASE_URL`; the `.env` file (with real credentials) is gitignored

## Testing

Tests should be placed in the root or a `tests/` directory. Use pytest-flask to test Flask routes.
## Authentication

Google OAuth is the only sign-in method. There is no password login, email
verification, or password reset, and no outbound email. `users.password_hash`
is legacy/nullable and never read. Legacy `auth_tokens` can be dropped manually
with `DROP TABLE IF EXISTS auth_tokens;`.
