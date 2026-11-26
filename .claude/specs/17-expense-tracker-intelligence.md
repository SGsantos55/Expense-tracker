---
# Spec: Expense Tracker Intelligence

## Overview
Expense Tracker Intelligence adds a financial overview and optional follow-up chat to
Expense Tracker. It is built on **one shared, deterministic analytics layer**
and two LangGraph workflows:

1. **Financial Summary Graph** — turns verified income, expense, budget and
   trend facts into a structured narrative with cautious, data-supported
   suggestions.
2. **Financial Chat Graph** — answers follow-up questions using the same facts
   and a small, read-only tool allowlist.

The summary is the primary product; chat is an optional extension shown
underneath it. The page must be useful **without any AI provider configured**:
deterministic totals, budget status, category breakdowns and rule-based
insights always render. AI only adds narrative, prioritisation and
conversational answers.

The assistant is an **analytical assistant, not a financial advisor**. It
explains recorded data first and may add cautious suggestions that are tied to
a detected insight. It must never give investment, loan, tax, legal or medical
advice, and must never claim guaranteed outcomes. A persistent disclaimer is
shown on the page.

Summaries support multiple periods, not only months:
- This week
- This month (the user's **financial month**, honouring `financial_month_start_day`)
- Last month (previous complete financial month)
- Custom date range
- Year to date

This works with the user's existing Settings data: income history, overall
monthly budget, per-category limits, actual expenditure, remaining budget and
spending trends. Expense Tracker already runs on **PostgreSQL via psycopg 3**; this
feature must not introduce SQLite, a second backend service, a vector database,
RAG, multi-agent orchestration or human-in-the-loop approval.

## Depends on
- Step 01 — Profile & Financial Settings (preferences, income, budgets,
  categories) — complete.
- Steps 02/03 — registration, login and session auth — complete.
- Steps 05/06 — live profile data and date filtering — complete.
- Steps 07/08/09 — add/edit/delete expense — complete.
- Step 14 — delete user (must be extended to remove AI rows) — complete.
- Step 15 — PostgreSQL/psycopg migration — complete.
- No dependency on the export features (Steps 11/16).

## Routes
All routes are logged-in only. HTML routes redirect to `login` when
`g.user_id` is missing; JSON routes return `401 application/json`.

- `GET /insights` — Expense Tracker Intelligence page. Query params: `preset`
  (`this_week|this_month|last_month|custom|ytd`, default `this_month`),
  `date_from`, `date_to` (ISO `YYYY-MM-DD`, required for `custom`). Invalid
  values fall back to `this_month` with a flash message. Always computes
  deterministic facts and renders them; only loads a cached AI narrative if a
  matching cached summary exists. **Never calls the LLM on GET.**
- `POST /insights/summary` — form-encoded `preset`, `date_from`, `date_to`,
  optional `force=1`. Resolves the period, calls the Summary Graph (or a
  cached result), persists the summary, flashes success/degraded state, and
  redirects back to `/insights` with the same period. `force=1` bypasses the
  cache.
- `POST /insights/chat` — JSON body:
  `{"message": "...", "preset": "...", "date_from": "...", "date_to": "..."}`.
  Returns `200 {"answer": "...", "follow_up_suggestions": [...], "period":
  {...}}`; `400` for invalid JSON/message/period; `401` unauthenticated;
  `429` rate-limited; `503` when AI is disabled/unconfigured (chat requires
  the LLM; deterministic summaries do not).
- `POST /insights/chat/clear` — clears the current user's chat session and
  returns `204` (JSON) or redirects back to `/insights` for form fallback.

No public routes.

## Database changes
Add the following tables in `database/db.py` inside `init_db()`, using
`CREATE TABLE IF NOT EXISTS` and idempotent migrations like the existing
schema. Dates remain ISO `TEXT` to match the rest of the app.

```sql
CREATE TABLE IF NOT EXISTS ai_summaries (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    period_preset TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    facts JSONB NOT NULL,
    summary JSONB NOT NULL,
    data_fingerprint TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model TEXT NOT NULL,
    generated_at TEXT NOT NULL DEFAULT (now()::text),
    UNIQUE (user_id, period_start, period_end, prompt_version, model)
);

CREATE TABLE IF NOT EXISTS ai_chat_sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    period_start TEXT,
    period_end TEXT,
    created_at TEXT NOT NULL DEFAULT (now()::text),
    updated_at TEXT NOT NULL DEFAULT (now()::text)
);

CREATE TABLE IF NOT EXISTS ai_chat_messages (
    id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES ai_chat_sessions(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (now()::text)
);

CREATE TABLE IF NOT EXISTS ai_usage (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL CHECK (kind IN ('summary', 'chat')),
    model TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (now()::text)
);
```

Add indexes:
- `ai_summaries (user_id, period_start, period_end)`
- `ai_chat_sessions (user_id)`
- `ai_chat_messages (session_id, created_at)`
- `ai_usage (user_id, created_at)`

Update `database/queries.py::delete_user()` to delete AI data first, before
`users`:
`ai_chat_messages` → `ai_chat_sessions` → `ai_summaries` → `ai_usage` →
existing tables.

Update `tests/conftest.py` TRUNCATE list to include the four AI tables
(`ai_usage, ai_chat_messages, ai_chat_sessions, ai_summaries`) so tests stay
deterministic.

## Templates
- **Create:**
  - `templates/insights/index.html` — page extending `base.html`; period
    selector, overview cards, category budget table, insights, AI narrative,
    chat panel, disclaimer.
  - `templates/insights/_summary.html` — reusable summary/overview partial
    (facts, insights, cached narrative, Generate/Regenerate state, fallback
    badge).
  - `templates/insights/_chat.html` — chat messages, suggested prompts,
    input, disabled state, clear action.
- **Modify:**
  - `templates/base.html` — add an “Insights” nav link for logged-in users
    (between Profile and Settings). Do not show it to anonymous visitors.
  - `templates/privacy.html` — add an AI processing section: what is sent to
    the model provider (aggregated financial facts, and limited transaction
    matches when the user asks), that the provider must not train on it, that
    the key is server-side, and that deterministic features work without AI.

## Files to change
- `app.py` — import `jsonify`; register the four routes; read `AI_ENABLED`
  for template context; call `ai.service` functions; keep the existing auth
  and flash patterns. Do not put analytics or prompt logic in `app.py`.
- `database/db.py` — add AI tables and indexes; add any idempotent migration
  needed for existing databases.
- `database/queries.py` — extend `delete_user()` for AI tables.
- `tests/conftest.py` — truncate AI tables per test.
- `requirements.txt` — add AI dependencies (see below).
- `.env.example` — document all AI environment variables (see below).
- `templates/base.html` — Insights nav link.
- `templates/privacy.html` — AI disclosure.
- `CLAUDE.md` — document the `ai/` package, AI env vars, the “Python owns the
  numbers” rule, and how tests fake the LLM.
- `static/css/style.css` — only if a shared nav style needs a tiny addition;
  prefer `static/css/insights.css`.

## Files to create
- `ai/__init__.py`
- `ai/config.py` — env parsing and `AI_ENABLED`/`AI_CONFIGURED` helpers.
- `ai/periods.py` — pure period resolution, financial-month buckets,
  day-overlap helpers, comparison periods, validation, labels.
- `ai/analytics.py` — deterministic facts: income, expenses, budgets,
  category breakdown, remaining budget, trends. Uses psycopg parameterised
  queries only.
- `ai/insights.py` — rule-based insight detection with stable insight IDs,
  severity and the exact metrics that back each insight.
- `ai/schemas.py` — Pydantic models for summary output, chat answer,
  recommendation and tool results.
- `ai/validation.py` — schema validation, numeric-grounding checks,
  advice/scope checks and fallback summary builder.
- `ai/llm.py` — the only provider-specific file; returns a configured Groq
  chat model via `langchain-groq`/`AI_MODEL`, or `None` when disabled. No
  network call at import time.
- `ai/prompts.py` — versioned summary, scope/intent, chat and validation-repair
  prompts. No secrets.
- `ai/tools.py` — read-only tool functions with `user_id` and period injected
  by the executor, never by the model.
- `ai/rate_limit.py` — per-user summary/chat limits (simple DB- or
  process-local implementation; document the production Redis swap).
- `ai/service.py` — public orchestration API used by `app.py`: resolve period,
  load facts, get/create cached summary, run chat, clear chat, enabled flags.
- `ai/graphs/__init__.py`
- `ai/graphs/state.py` — `SummaryState` and `ChatState` `TypedDict`s.
- `ai/graphs/summary_graph.py` — LangGraph summary workflow.
- `ai/graphs/chat_graph.py` — LangGraph chat workflow.
- `database/ai_queries.py` — persistence for summaries, chat sessions/messages
  and usage; all parameterised.
- `static/css/insights.css` — page styles using existing CSS variables.
- `static/js/insights.js` — period/custom-range UI, chat fetch, loading/error
  states, suggested prompts, clear chat, safe text rendering.
- `tests/test_ai_periods.py` — preset, financial-month and proration tests.
- `tests/test_ai_analytics.py` — facts and insight rules against a known
  dataset.
- `tests/test_ai_summary.py` — graph, schema, cache, validation, fallback.
- `tests/test_ai_chat.py` — scope refusal, routing, grounding, history and
  user isolation.
- `tests/test_ai_routes.py` — auth, JSON validation, rate limits, disabled
  mode.
- `tests/ai_fakes.py` — fake chat model / scripted responses; no network.

## New dependencies
Add to `requirements.txt` (pin versions at implementation time):
- `langgraph` — orchestration.
- `langchain-groq` — Groq chat model adapter (brings
  `langchain-core`/`groq` transitively).
- `pydantic` — typed structured outputs.

Deliberately **not** added: vector databases, embedding packages, RAG
frameworks, multi-agent frameworks, Redis (until rate limiting needs it in
production). `requests` is already present.

## Rules for implementation
All existing rules still apply: no SQLAlchemy or ORMs; parameterised psycopg
queries only; passwords hashed with werkzeug; CSS variables and never
hardcoded hex values; every template extends `base.html`.

### Non-negotiable architecture
1. **Python owns the numbers. The LLM owns the explanation.** Totals,
   percentages, remaining budget, trends and deltas are computed in
   `ai/analytics.py`/`ai/insights.py`. The LLM must never calculate them.
2. **LangGraph owns orchestration, not business logic.** Graph nodes call the
   shared analytics/services layer. Analytics functions must work without
   LangGraph and be independently testable.
3. **The backend owns security.** `user_id` comes from `g.user_id`/the Flask
   session, never from the LLM or request body for tool execution. Tool
   permissions, ownership checks and parameterised SQL are the real boundary;
   prompts are not a security boundary.
4. **No RAG, vector DB, multi-agent or HITL in v1.** The data is structured.
   Use tools and precomputed facts. HITL becomes relevant only if write
   actions are added later.
5. **Summary = one LLM call** (Option A). Compute everything in Python, send a
   compact facts object, receive structured JSON. Do not split the summary
   into multiple specialised calls.
6. **Chat = constrained tool routing** (`max 2 LLM calls`: optional
   classify/route + compose). Do not build a free ReAct agent that decides
   arbitrary tools.

### Periods and money semantics
- Presets:
  - `this_week`: Monday through today inclusive.
  - `this_month`: the current financial month using
    `_financial_month_range(today, financial_month_start_day)`.
  - `last_month`: the previous complete financial month.
  - `custom`: inclusive `date_from`..`date_to`, `date_from <= date_to`,
    `date_to` not in the future, at most 366 days.
  - `ytd`: 1 January of the current calendar year through today.
- Use server-local `date.today()` as the existing app does, but pass `today`
  into period functions so tests are deterministic. Never call `date.today()`
  inside pure analytics helpers.
- **Budget allowance:** budgets are monthly and reset on financial-month
  boundaries. If the selected period is exactly one financial month, the
  allowance is the full monthly limit (`budget_basis="full_month"`).
  Otherwise prorate each intersected financial month by
  `overlap_days / days_in_financial_month`, sum the buckets
  (`budget_basis="prorated"`). Apply the same rule to category limits.
- **Income allowance:** `income_entries.effective_month` is monthly
  (`YYYY-MM`). If the period covers a full calendar month, include the full
  entry. Otherwise allocate each entry by
  `overlap_days / days_in_calendar_month` and sum
  (`income_basis="prorated"`). This avoids counting two full salaries when a
  financial month spans two calendar months. Label prorated income clearly in
  the UI.
- `remaining_budget = allowance - expenses`; `remaining_category =
  category_allowance - category_spend`. Negative values are allowed and shown
  as over budget, not clamped.
- Use `Decimal(str(value))` for allocation/rounding to avoid float artefacts;
  round user-facing money to 2 decimals and percentages to 1 decimal.
- Comparison periods: previous financial month for month presets; previous
  7 days for `this_week`; immediately preceding equal-length range for
  `custom`; same calendar range in the previous year for `ytd`. If a previous
  value is zero, report “new” rather than an infinite percentage.

### Facts every summary must include
Return one JSON-serialisable `facts` object (stored in `ai_summaries.facts`):
- Period: preset, start, end, label, `budget_basis`, `income_basis`,
  comparison label.
- Currency code + symbol and the user's date/number formats (for prompt-side
  formatting).
- Income: amount, basis, entry count.
- Expenses: total, transaction count, by category, top category, daily totals
  (bounded to the period; no raw rows).
- Budget: overall limit, allowance, spent, remaining, utilisation, status
  (`ok|near_limit|over|no_budget`), and per-category rows with the same fields
  plus archived/unbudgeted flags.
- Comparison: previous period totals, overall delta, per-category deltas.
- Insights: stable IDs, severity (`info|warning|critical`), kind, title,
  short message, and the exact metric values backing each insight.
- Data quality: `has_expenses`, `has_income`, `has_budget`,
  `has_categories`, `uncategorized_spend`.

Never send raw transaction rows in the summary context. For chat, send only
the tool results needed for that answer; `search_transactions` is capped at 20
rows and returns date/category/amount/description only.

### Insight rules (deterministic)
At minimum:
- Overall over budget / near limit (>= 90%).
- Each category over budget / near limit.
- Largest category share of spend.
- Category increase vs comparison period (>= 15% and a meaningful absolute
  increase).
- Income change vs comparison period.
- Savings/surplus or deficit (income − expenses).
- Unbudgeted categories with meaningful spend.
- No budget set, no income recorded, or no expenses in the period.
Keep insight IDs stable (e.g. `overall_over_budget`, `category_over:Food`,
`category_up:Food`) so recommendations can reference them.

### Summary Graph
Use a LangGraph `StateGraph` with `SummaryState`:
`user_id, preset, date_from, date_to, prefs, period, facts, insights,
cache_key, summary, validation_errors, attempts, model, usage, degraded,
status`.

Nodes and edges:
1. `resolve_period` — validate preset/range, resolve start/end/labels.
2. `load_context` — preferences, categories, budgets (no LLM).
3. `compute_facts` — analytics + insight detection.
4. `check_cache` — fingerprint match? If yes and not forced, skip to persist.
5. `generate_summary` — **one** structured-output LLM call using the facts and
   insight IDs.
6. `validate_summary` — schema, numeric grounding, recommendation linkage,
   advice/scope checks.
7. Conditional edge: valid → `persist`; invalid and `attempts < 2` → retry
   once with validation errors; otherwise → `fallback`.
8. `fallback` — deterministic narrative built from facts/insights, marked
   `degraded=true`.
9. `persist` — upsert by `(user_id, period_start, period_end, prompt_version,
   model)`; record usage.

LLM/network failure must go straight to `fallback`; never return a 500.

### Summary output schema
Use Pydantic and structured JSON:

```python
class Recommendation(BaseModel):
    insight_id: str
    text: str

class FinancialSummary(BaseModel):
    overview: str                 # 2-4 sentences
    key_findings: list[str]       # max 5
    budget_analysis: str          # 1-3 sentences
    category_analysis: list[str]  # max 5
    recommendations: list[Recommendation]  # max 3
    warnings: list[str]           # max 3
```

Validation must:
- Enforce list/string limits and non-empty required fields.
- Extract money/percentage claims and require each to exist in the allowed
  formatted values/percentages from `facts` (tolerance only for rounding
  already encoded in the allowed set).
- Require every `Recommendation.insight_id` to exist in `facts["insights"]`.
- Reject advice about investments, loans, tax, legal, medical, or guaranteed
  outcomes; require cautious language (“consider”, “you could”, “based on
  your data”).
- Reject off-scope content.
If validation fails after one repair attempt, use the deterministic fallback.

### Chat Graph
Use a separate `StateGraph` with `ChatState`:
`user_id, session_id, message, preset, date_from, date_to, prefs, period,
intent, scope_ok, tool_results, answer, validation_errors, attempts, usage,
status`.

Nodes and edges:
1. `guard_input` — validate JSON, message length 1-500, auth, rate limit.
2. `classify_scope` — financial intent allowlist. Start with deterministic
   keyword/rules routing; optionally one small structured LLM classifier.
   If uncertain or disabled, **fail closed** with the predefined refusal.
3. `resolve_period` — default to the page's period; allow “this week”, “last
   month”, etc. only if they map to valid presets, otherwise keep the current
   period.
4. `route_tools` — map intent to zero or more allowlisted tools.
5. `execute_tools` — inject `user_id` and period from state; validate args;
   read-only; cap results.
6. `compose_answer` — one LLM call with tool results, current facts and a
   short conversation history.
7. `validate_answer` — numeric grounding, scope, length, cautious language.
   Retry once, then return a safe grounded fallback/refusal.
8. `persist_messages` — store user and assistant messages; update session.

Tools (all read-only, all inject `user_id` server-side):
- `get_income_summary(period)`
- `get_expense_summary(period)`
- `get_budget_status(period)`
- `get_category_breakdown(period)`
- `compare_periods(period_a, period_b)`
- `search_transactions(period, category?, text?, min_amount?, max_amount?, limit)`
- `get_financial_insights(period)`
- `what_if_reduce_category(category, percent, period)` — deterministic only.

Never expose a general SQL tool, writes, account actions or another user's
data. If a user asks to change/delete something, explain where to do it in
the app; do not perform it.

### Scope and safety
- Intent allowlist: overview, income, expenses, budget status, category
  analysis, period comparison, transaction search, insights, what-if.
- Everything else gets one predefined refusal, e.g. “I can only help with
  your recorded expenses, income, budgets and spending trends.” Do not answer
  general knowledge, coding, news, medical, legal or investment questions.
- Treat user text as untrusted data. Never reveal system prompts, internal
  instructions, tool schemas or model configuration. Detect and refuse prompt
  injection/role-change attempts.
- Render all model output with Jinja autoescaping, and in JavaScript use
  `textContent`/`createTextNode` — never `innerHTML` for model output.
- JSON chat route: require `Content-Type: application/json`, validate the
  body, check same-origin (`Origin`/`Referer` host against `request.host`),
  and keep the session cookie `SameSite=Lax` (set if not already).
- Log only metadata (kind, model, tokens, latency, error class). Never log
  prompts, full answers or financial amounts.

### Caching, persistence and cost
- GET `/insights` never calls the LLM. It computes cheap facts and reads a
  cached summary by fingerprint.
- Fingerprint = SHA-256 of a canonical JSON payload containing: prompt
  version, model, user preferences, category names, budget rows, and
  user-scoped expense/income count + max id + sum. Any data change therefore
  invalidates the cache automatically; no route hooks are required.
- `POST /insights/summary` reuses a matching fingerprint unless `force=1`.
- Store one summary per `(user_id, period_start, period_end, prompt_version,
  model)`; upsert on regeneration.
- Chat uses fresh tool data; it may also reference the cached summary, but
  must not treat stale summary text as authoritative over tool results.
- Conversation history: last 20 messages per session, server-side only.
  Generate the session ID server-side and store it in the Flask session;
  never trust a client-supplied `user_id`.
- Rate limits (configurable): summaries 5/hour, chat 10/minute and 200/day per
  user. Return `429` with a friendly message. Quotas are recorded in
  `ai_usage`.
- Timeouts 30s; one retry for transient transport errors; no retry loops
  around validation beyond the single repair attempt.
- `AI_ENABLED=false` or a missing key: summaries use the deterministic
  fallback, chat returns `503`, and the UI shows a clear notice. No external
  request is made.

### Environment variables (add to `.env.example`)
```
AI_ENABLED=false
GROQ_API_KEY=
AI_MODEL=qwen/qwen3.8-27b
AI_TIMEOUT_SECONDS=30
AI_MAX_OUTPUT_TOKENS=1200
AI_TEMPERATURE=0.2
AI_SUMMARY_PROMPT_VERSION=summary-v1
AI_CHAT_PROMPT_VERSION=chat-v1
AI_SUMMARY_LIMIT_PER_HOUR=5
AI_CHAT_LIMIT_PER_MINUTE=10
AI_CHAT_LIMIT_PER_DAY=200
AI_MAX_PERIOD_DAYS=366
BUDGET_WARNING_THRESHOLD=90
```
Never commit a real key. `ai/llm.py` is the only file that reads the key and
constructs the provider client.

### UI/UX
- Header: “Expense Tracker Intelligence”, subtitle, period selector (presets +
  custom date inputs), and a visible period label.
- Overview cards: Income, Total expenditure, Remaining budget, Savings
  (income − expenses). When prorated, show a small “Prorated for this period”
  note and the basis.
- Category rows: category, spent, limit, remaining, utilisation bar, status
  (ok / near limit / over / no budget). Use `--neon-green`, `--accent-2` for
  near-limit and `--danger` for over.
- “AI-generated insights”: cached narrative sections (overview, key findings,
  budget analysis, category analysis, recommendations, warnings). Show a
  “Generate summary” button when absent and “Regenerate” when present. Show a
  subtle “Computed summary (AI unavailable)” badge when `degraded`.
- Chat: “Ask about your finances” with 3 suggested prompts; disabled state
  explaining AI is not configured; message history; loading state; clear
  button.
- Persistent disclaimer: “Expense Tracker Intelligence explains your recorded data.
  It is not financial advice.”
- Empty states: no expenses / no income / no budget, each with a link to the
  relevant page.
- Mobile responsive, keyboard accessible, `aria-live` for chat, focus states.
  Use CSS variables only; no hardcoded hex; no Tailwind/React/Bootstrap.
  Re-run `lucide.createIcons()` after dynamic renders.

### Testing and evaluation
- No real network calls in tests. `tests/ai_fakes.py` provides a scripted chat
  model; monkeypatch `ai.llm.get_chat_model` or inject it into the service.
- Build a golden fixture user with known income, budgets and expenses in
  several months. Assert facts, proration, deltas, insight IDs and remaining
  budget against hand-calculated values.
- Test validation with: valid output, invented number, invalid insight ID,
  investment advice, off-topic answer, malformed JSON.
- Test chat: budget question, category question, comparison, transaction
  search, off-topic refusal, prompt injection, history, user A/B isolation.
- Test routes: logged-out redirects, JSON 400/401/429/503, disabled mode,
  cache reuse (LLM called once), force regeneration, fallback on provider
  error.
- Keep the existing suite green. Update `tests/conftest.py` for the new
  tables.

## Definition of done
- [x] `pytest` passes: all existing tests plus the new AI tests, with no real
      API calls and no network dependency.
- [x] Database migration creates `ai_summaries`, `ai_chat_sessions`,
      `ai_chat_messages`, `ai_usage` and their indexes on both fresh and
      existing databases.
- [x] Deleting an account removes all AI summaries, sessions, messages and
      usage rows with no FK errors.
- [x] `/insights` redirects anonymous users to login; logged-in users see the
      page with the Insights nav link.
- [x] Period resolution works for this week, this month, last month, custom
      and YTD. “This month”/“last month” honour `financial_month_start_day`
      (tested with day 25). Invalid custom ranges fall back with a flash.
- [x] Summary numbers for the seeded user exactly match direct SQL totals
      (income, expenses, category totals, budget remaining); no LLM arithmetic
      is trusted.
- [x] Budget and income proration is correct for partial periods, with the
      `full_month`/`prorated` basis shown in the UI.
- [x] The summary shows income, total expenditure, remaining budget,
      category limits/remaining and spending trends for every preset.
- [x] The AI summary returns the documented schema; every amount/percentage
      is grounded in facts; every recommendation references a valid insight.
- [x] Cached summaries are reused (LLM called once); `force=1` regenerates;
      a changing expense/income/budget invalidates the fingerprint.
- [x] Provider failure, timeout, malformed JSON and validation failure render
      the deterministic fallback with a degraded badge — never a 500.
- [x] AI-disabled mode renders deterministic facts/insights and disables
      chat with a clear notice; no external request is made.
- [x] Chat answers budget, category, comparison and transaction questions
      using tools; figures match the database; follow-up suggestions render.
- [x] Off-topic questions and prompt-injection attempts receive the
      predefined refusal and cannot access another user's data.
- [x] Chat history persists per session, is capped, and can be cleared.
- [x] Summary (5/hour), chat (10/minute, 200/day) limits return 429 when
      exceeded.
- [x] No API key, prompt or internal configuration appears in HTML, JS, logs
      or error messages.
- [x] The AI processing disclosure is present in the privacy policy.
- [x] The page is mobile responsive, uses only CSS variables (no hardcoded
      hex), uses Lucide icons, and safely renders model output without
      `innerHTML`.
- [x] `CLAUDE.md` and `.env.example` document the AI module, environment
      variables and how to run/mocking tests.
