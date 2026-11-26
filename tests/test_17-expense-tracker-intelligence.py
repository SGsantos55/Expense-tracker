"""Tests for Step 17: Expense Tracker Intelligence (/insights, summary, chat).

Written from .claude/specs/17-expense-tracker-intelligence.md.  No network
access: the LLM is always faked (tests/ai_fakes.py) or the service layer is
stubbed.  The autouse fixtures in tests/conftest.py reset the Postgres test
database (including the AI tables) before every test.
"""
import json
from datetime import date

import psycopg
import pytest

from tests.ai_fakes import FakeChatModel, valid_summary_json

SEED_EMAIL = "plankmax05@gmail.com"
LOCAL_ORIGIN = "http://localhost"


# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------

@pytest.fixture
def app():
    from app import app as flask_app
    flask_app.config.update({"TESTING": True, "SECRET_KEY": "test-secret"})
    return flask_app


@pytest.fixture
def client(app):
    test_client = app.test_client()
    test_client.environ_base["HTTP_ORIGIN"] = "http://localhost"
    return test_client


def _query(sql, params=()):
    from database.db import get_db
    conn = get_db()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def _execute(sql, params=()):
    from database.db import get_db
    conn = get_db()
    try:
        row = conn.execute(sql, params)
        result = row.fetchone() if row.description else None
        conn.commit()
        return result
    finally:
        conn.close()


def _create_user(email="other@example.com", name="Other User"):
    row = _execute(
        "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s) "
        "RETURNING id",
        (name, email, "x"),
    )
    return row["id"]


def _add_expense(user_id, amount, day, category="Food", description="t"):
    _execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (%s, %s, %s, %s, %s)",
        (user_id, amount, category, day, description),
    )


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    return client


@pytest.fixture
def seed_user_id():
    return _query("SELECT id FROM users WHERE email = %s", (SEED_EMAIL,))[0]["id"]


@pytest.fixture
def auth_client(client, seed_user_id):
    return _login(client, seed_user_id)


@pytest.fixture
def ai_on(monkeypatch):
    """Enable AI with a scripted fake model; returns the fake."""
    import ai.service as service
    fake = FakeChatModel([valid_summary_json()] * 5)
    monkeypatch.setattr(service, "is_available", lambda: True)
    monkeypatch.setattr(service, "get_chat_model", lambda: fake)
    return fake


@pytest.fixture
def ai_off(monkeypatch):
    import ai.service as service

    def _no_model():
        raise AssertionError("LLM must not be constructed when AI is disabled")

    import ai.config as ai_config

    monkeypatch.setattr(ai_config, "AI_ENABLED", False)
    monkeypatch.setattr(ai_config, "GROQ_API_KEY", "")
    monkeypatch.setattr(service, "is_available", lambda: False)
    monkeypatch.setattr(service, "get_chat_model", _no_model)


def _summary_rows(user_id):
    return _query("SELECT * FROM ai_summaries WHERE user_id = %s", (user_id,))


def _chat_post(client, payload, origin=LOCAL_ORIGIN, **kwargs):
    headers = {"Origin": origin or ""}
    return client.post("/insights/chat", json=payload, headers=headers, **kwargs)


# --------------------------------------------------------------------------
# Database schema
# --------------------------------------------------------------------------

class TestSchema:
    @pytest.mark.parametrize(
        "table", ["ai_summaries", "ai_chat_sessions", "ai_chat_messages", "ai_usage"]
    )
    def test_ai_table_exists(self, table):
        rows = _query(
            "SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table,)
        )
        assert rows, f"Expected table {table} to exist"

    @pytest.mark.parametrize(
        "table,columns",
        [
            ("ai_summaries", ["user_id", "period_start", "period_end"]),
            ("ai_chat_sessions", ["user_id"]),
            ("ai_chat_messages", ["session_id", "created_at"]),
            ("ai_usage", ["user_id", "created_at"]),
        ],
    )
    def test_required_index_exists(self, table, columns):
        defs = [r["indexdef"] for r in _query(
            "SELECT indexdef FROM pg_indexes WHERE tablename = %s", (table,))]
        wanted = "(" + ", ".join(columns) + ")"
        assert any(wanted in d for d in defs), (
            f"Expected an index on {table}{wanted}; found {defs}"
        )

    def test_init_db_is_idempotent(self):
        from database.db import init_db
        init_db()
        init_db()  # must not raise

    def test_summary_unique_per_user_period_prompt_model(self, seed_user_id):
        sql = (
            "INSERT INTO ai_summaries (user_id, period_preset, period_start, "
            "period_end, facts, summary, data_fingerprint, prompt_version, model) "
            "VALUES (%s, 'this_month', '2025-01-01', '2025-01-31', "
            "'{}'::jsonb, '{}'::jsonb, 'fp', 'v1', 'm')"
        )
        _execute(sql, (seed_user_id,))
        with pytest.raises(psycopg.errors.UniqueViolation):
            _execute(sql, (seed_user_id,))

    def test_chat_message_role_check_constraint(self, seed_user_id):
        _execute("INSERT INTO ai_chat_sessions (id, user_id) VALUES ('s1', %s)",
                 (seed_user_id,))
        with pytest.raises(psycopg.errors.CheckViolation):
            _execute(
                "INSERT INTO ai_chat_messages (session_id, user_id, role, content) "
                "VALUES ('s1', %s, 'system', 'hi')",
                (seed_user_id,),
            )

    def test_usage_kind_check_constraint(self, seed_user_id):
        with pytest.raises(psycopg.errors.CheckViolation):
            _execute("INSERT INTO ai_usage (user_id, kind) VALUES (%s, 'bogus')",
                     (seed_user_id,))


# --------------------------------------------------------------------------
# Period resolution (pure, deterministic via injected `today`)
# --------------------------------------------------------------------------

class TestPeriods:
    TODAY = date(2026, 6, 17)  # a Wednesday

    def _resolve(self, preset, date_from=None, date_to=None, prefs=None, today=None):
        from ai.periods import resolve_period
        return resolve_period(preset, date_from, date_to, prefs=prefs or {},
                              today=today or self.TODAY)

    def test_this_week_is_monday_through_today(self):
        p = self._resolve("this_week")
        assert p.start == date(2026, 6, 15)
        assert p.end == self.TODAY

    def test_this_week_comparison_is_previous_seven_days(self):
        p = self._resolve("this_week")
        assert p.comparison_start == date(2026, 6, 8)
        assert p.comparison_end == date(2026, 6, 14)

    def test_this_month_default_start_day(self):
        p = self._resolve("this_month")
        assert (p.start, p.end) == (date(2026, 6, 1), date(2026, 6, 30))
        assert p.budget_basis == "full_month"

    def test_last_month_default_start_day(self):
        p = self._resolve("last_month")
        assert (p.start, p.end) == (date(2026, 5, 1), date(2026, 5, 31))
        assert p.budget_basis == "full_month"

    def test_this_month_honours_financial_month_start_day(self):
        p = self._resolve("this_month", prefs={"financial_month_start_day": 25})
        assert (p.start, p.end) == (date(2026, 5, 25), date(2026, 6, 24))

    def test_this_month_rolls_over_after_start_day(self):
        p = self._resolve("this_month", prefs={"financial_month_start_day": 25},
                          today=date(2026, 6, 26))
        assert (p.start, p.end) == (date(2026, 6, 25), date(2026, 7, 24))

    def test_last_month_honours_financial_month_start_day(self):
        p = self._resolve("last_month", prefs={"financial_month_start_day": 25})
        assert (p.start, p.end) == (date(2026, 4, 25), date(2026, 5, 24))

    def test_ytd_is_jan_first_through_today_and_prorated(self):
        p = self._resolve("ytd")
        assert (p.start, p.end) == (date(2026, 1, 1), self.TODAY)
        assert p.budget_basis == "prorated"

    def test_ytd_comparison_is_same_range_previous_year(self):
        p = self._resolve("ytd")
        assert p.comparison_start == date(2025, 1, 1)
        assert p.comparison_end == date(2025, 6, 17)

    def test_custom_valid_range_is_inclusive_and_prorated(self):
        p = self._resolve("custom", "2026-06-01", "2026-06-10")
        assert (p.start, p.end) == (date(2026, 6, 1), date(2026, 6, 10))
        assert p.budget_basis == "prorated"
        assert p.income_basis == "prorated"

    def test_custom_comparison_is_equal_length_preceding_range(self):
        p = self._resolve("custom", "2026-06-01", "2026-06-10")
        assert p.comparison_start == date(2026, 5, 22)
        assert p.comparison_end == date(2026, 5, 31)

    def test_custom_single_day_allowed(self):
        p = self._resolve("custom", "2026-06-10", "2026-06-10")
        assert p.start == p.end == date(2026, 6, 10)

    def test_custom_max_366_days_allowed(self):
        p = self._resolve("custom", "2025-06-01", "2026-06-01")
        assert (p.end - p.start).days + 1 == 366

    def test_full_calendar_month_income_is_not_prorated(self):
        p = self._resolve("custom", "2026-05-01", "2026-05-31")
        assert p.income_basis != "prorated"

    @pytest.mark.parametrize(
        "preset,date_from,date_to",
        [
            ("custom", "2026-06-10", "2026-06-01"),   # from after to
            ("custom", "2026-06-01", "2026-06-18"),   # to in the future
            ("custom", "2025-05-31", "2026-06-01"),   # 367 days
            ("custom", None, None),                   # missing dates
            ("custom", "2026-06-01", None),           # missing end
            ("custom", "06/01/2026", "06/10/2026"),   # wrong format
            ("custom", "not-a-date", "2026-06-10"),
            ("bogus", None, None),                    # unknown preset
        ],
    )
    def test_invalid_period_raises_period_error(self, preset, date_from, date_to):
        from ai.periods import PeriodError
        with pytest.raises(PeriodError):
            self._resolve(preset, date_from, date_to)


# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------

class TestAuthGuards:
    def test_insights_anonymous_redirects_to_login(self, client):
        resp = client.get("/insights")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_summary_anonymous_redirects_to_login(self, client):
        resp = client.post("/insights/summary", data={"preset": "this_month"})
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
        assert _query("SELECT 1 FROM ai_summaries") == []

    def test_chat_anonymous_returns_401_json(self, client):
        resp = client.post("/insights/chat", json={"message": "hi"})
        assert resp.status_code == 401
        assert resp.is_json, "401 must be application/json"

    def test_chat_clear_anonymous_json_returns_401(self, client):
        resp = client.post("/insights/chat/clear", json={})
        assert resp.status_code == 401
        assert resp.is_json

    def test_chat_clear_anonymous_form_redirects_to_login(self, client):
        resp = client.post("/insights/chat/clear")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


# --------------------------------------------------------------------------
# GET /insights page
# --------------------------------------------------------------------------

class TestInsightsPage:
    def test_logged_in_renders_page_with_header_and_disclaimer(self, auth_client, ai_off):
        resp = auth_client.get("/insights")
        assert resp.status_code == 200
        assert b"Expense Tracker Intelligence" in resp.data
        assert b"not financial advice" in resp.data.lower()

    @pytest.mark.parametrize("preset", ["this_week", "this_month", "last_month", "ytd"])
    def test_every_preset_renders(self, auth_client, ai_off, preset):
        resp = auth_client.get(f"/insights?preset={preset}")
        assert resp.status_code == 200, f"preset {preset} should render"

    def test_custom_valid_range_renders(self, auth_client, ai_off):
        resp = auth_client.get(
            "/insights?preset=custom&date_from=2025-03-01&date_to=2025-03-31")
        assert resp.status_code == 200
        assert b"2025-03-01" in resp.data

    @pytest.mark.parametrize(
        "query",
        [
            "preset=nonsense",
            "preset=custom",
            "preset=custom&date_from=2025-03-31&date_to=2025-03-01",
            "preset=custom&date_from=garbage&date_to=2025-03-01",
            "preset=custom&date_from=2025-01-01&date_to=2999-01-01",
            "preset=custom&date_from=2020-01-01&date_to=2025-03-01",
        ],
    )
    def test_invalid_period_falls_back_to_this_month_with_flash(
            self, auth_client, ai_off, query):
        resp = auth_client.get(f"/insights?{query}", follow_redirects=True)
        assert resp.status_code == 200
        assert b"this month" in resp.data.lower()
        assert b"Using this month instead" in resp.data

    def test_get_never_calls_llm(self, auth_client, monkeypatch):
        import ai.service as service

        def boom(*a, **k):
            raise AssertionError("GET /insights must not call the LLM")

        monkeypatch.setattr(service, "run_summary_graph", boom)
        monkeypatch.setattr(service, "run_chat_graph", boom)
        monkeypatch.setattr(service, "get_chat_model", boom)
        monkeypatch.setattr(service, "is_available", lambda: True)
        assert auth_client.get("/insights").status_code == 200

    def test_get_does_not_persist_a_summary(self, auth_client, seed_user_id, ai_off):
        auth_client.get("/insights")
        assert _summary_rows(seed_user_id) == []

    def test_no_summary_shows_generate_button(self, auth_client, ai_off):
        resp = auth_client.get("/insights")
        assert b"Generate summary" in resp.data

    def test_disabled_ai_still_renders_deterministic_content(self, auth_client, ai_off):
        resp = auth_client.get("/insights")
        assert resp.status_code == 200
        assert b"Category breakdown" in resp.data

    def test_disabled_ai_shows_chat_notice(self, auth_client, ai_off):
        body = auth_client.get("/insights").data.lower()
        assert b"ask about your finances" in body
        assert b"not configured" in body or b"unavailable" in body

    def test_enabled_ai_shows_suggested_prompts_and_chat(self, auth_client, ai_on):
        body = auth_client.get("/insights").data.lower()
        assert b"ask about your finances" in body

    def test_facts_match_direct_totals_for_known_user(self, client, ai_off):
        uid = _create_user()
        _add_expense(uid, 100.50, "2025-03-05", "Food")
        _add_expense(uid, 49.50, "2025-03-20", "Transport")
        _add_expense(uid, 999.00, "2025-04-02", "Food")  # outside period
        _login(client, uid)
        resp = client.get(
            "/insights?preset=custom&date_from=2025-03-01&date_to=2025-03-31")
        assert resp.status_code == 200
        assert b"150.00" in resp.data, "Total expenditure should be 150.00"
        assert b"999.00" not in resp.data, "Out-of-period expense must be excluded"

    def test_other_users_data_is_not_shown(self, client, ai_off):
        uid = _create_user("a@example.com", "A")
        other = _create_user("b@example.com", "B")
        _add_expense(other, 7777.77, "2025-03-05")
        _login(client, uid)
        resp = client.get(
            "/insights?preset=custom&date_from=2025-03-01&date_to=2025-03-31")
        assert b"7777.77" not in resp.data
        assert b"7,777.77" not in resp.data

    def test_nav_link_visible_to_logged_in_user_between_profile_and_settings(
            self, auth_client, ai_off):
        html = auth_client.get("/insights").data.decode()
        profile = html.find('href="/profile"')
        insights = html.find('href="/insights"')
        settings = html.find('href="/settings"')
        assert -1 not in (profile, insights, settings), "nav links missing"
        assert profile < insights < settings, "Insights link must sit between them"

    def test_nav_link_hidden_from_anonymous_visitors(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200
        assert b'href="/insights"' not in resp.data

    def test_privacy_page_has_ai_disclosure(self, client):
        resp = client.get("/privacy")
        assert resp.status_code == 200
        assert b"AI" in resp.data
        assert b"train" in resp.data.lower()


# --------------------------------------------------------------------------
# POST /insights/summary
# --------------------------------------------------------------------------

class TestSummaryRoute:
    def test_generate_persists_summary_and_redirects_to_same_period(
            self, auth_client, seed_user_id, ai_on):
        resp = auth_client.post("/insights/summary", data={"preset": "ytd"})
        assert resp.status_code == 302
        assert "/insights" in resp.headers["Location"]
        assert "preset=ytd" in resp.headers["Location"]
        rows = _summary_rows(seed_user_id)
        assert len(rows) == 1
        assert rows[0]["period_preset"] == "ytd"
        assert len(ai_on.calls) == 1, "Summary must use exactly one LLM call"

    def test_custom_period_is_preserved_in_redirect(self, auth_client, ai_on):
        resp = auth_client.post("/insights/summary", data={
            "preset": "custom", "date_from": "2025-03-01", "date_to": "2025-03-31"})
        assert resp.status_code == 302
        location = resp.headers["Location"]
        assert "2025-03-01" in location and "2025-03-31" in location

    def test_generated_summary_is_shown_with_regenerate_button(
            self, auth_client, ai_on):
        auth_client.post("/insights/summary", data={"preset": "this_month"})
        resp = auth_client.get("/insights?preset=this_month")
        assert b"Your recorded activity is shown above." in resp.data
        assert b"Regenerate" in resp.data

    def test_second_post_reuses_cache_llm_called_once(
            self, auth_client, seed_user_id, ai_on):
        auth_client.post("/insights/summary", data={"preset": "this_month"})
        auth_client.post("/insights/summary", data={"preset": "this_month"})
        assert len(ai_on.calls) == 1, "Cached summary must be reused"
        assert len(_summary_rows(seed_user_id)) == 1

    def test_force_regenerates_and_upserts_single_row(
            self, auth_client, seed_user_id, ai_on):
        auth_client.post("/insights/summary", data={"preset": "this_month"})
        auth_client.post("/insights/summary",
                         data={"preset": "this_month", "force": "1"})
        assert len(ai_on.calls) == 2, "force=1 must bypass the cache"
        assert len(_summary_rows(seed_user_id)) == 1, "Summary should be upserted"

    def test_data_change_invalidates_cache(self, auth_client, seed_user_id, ai_on):
        auth_client.post("/insights/summary", data={"preset": "this_month"})
        _add_expense(seed_user_id, 12.34, date.today().isoformat())
        auth_client.post("/insights/summary", data={"preset": "this_month"})
        assert len(ai_on.calls) == 2, "Changed expenses must invalidate the cache"

    def test_cached_summary_hidden_after_data_change(
            self, auth_client, seed_user_id, ai_on):
        auth_client.post("/insights/summary", data={"preset": "this_month"})
        _add_expense(seed_user_id, 12.34, date.today().isoformat())
        resp = auth_client.get("/insights?preset=this_month")
        assert b"Your recorded activity is shown above." not in resp.data
        assert b"Generate summary" in resp.data

    def test_ai_disabled_uses_deterministic_fallback_without_llm(
            self, auth_client, seed_user_id, ai_off):
        resp = auth_client.post("/insights/summary", data={"preset": "this_month"})
        assert resp.status_code == 302
        rows = _summary_rows(seed_user_id)
        assert len(rows) == 1, "Fallback summary should still be persisted"
        summary = rows[0]["summary"]
        assert summary.get("degraded") is True

    def test_degraded_badge_shown_after_fallback(self, auth_client, ai_off):
        auth_client.post("/insights/summary", data={"preset": "this_month"})
        resp = auth_client.get("/insights?preset=this_month")
        assert b"Computed summary (AI unavailable)" in resp.data

    @pytest.mark.parametrize(
        "responses",
        [
            [RuntimeError("provider down")],
            [TimeoutError("timeout")],
            ["this is not json"],
            ['{"overview": ""}'],
            [json.dumps({
                "overview": "You spent $999999.99 in total.",
                "key_findings": [], "budget_analysis": "Fine.",
                "category_analysis": [], "recommendations": [], "warnings": []})],
            [json.dumps({
                "overview": "Your recorded activity is shown above.",
                "key_findings": [], "budget_analysis": "Fine.",
                "category_analysis": [],
                "recommendations": [{"insight_id": "does_not_exist",
                                     "text": "You could review this."}],
                "warnings": []})],
            [json.dumps({
                "overview": "Your recorded activity is shown above.",
                "key_findings": [], "budget_analysis": "Fine.",
                "category_analysis": [], "recommendations": [],
                "warnings": ["Buy stocks and invest in crypto for guaranteed returns."]})],
        ],
        ids=["provider_error", "timeout", "malformed_json", "empty_required_field",
             "invented_number", "invalid_insight_id", "investment_advice"],
    )
    def test_provider_or_validation_failure_falls_back_never_500(
            self, auth_client, seed_user_id, monkeypatch, responses):
        import ai.service as service
        fake = FakeChatModel(responses)
        monkeypatch.setattr(service, "is_available", lambda: True)
        monkeypatch.setattr(service, "get_chat_model", lambda: fake)
        resp = auth_client.post("/insights/summary", data={"preset": "this_month"})
        assert resp.status_code == 302, "Failure must degrade gracefully, not 500"
        assert len(fake.calls) <= 2, "At most one repair attempt is allowed"
        rows = _summary_rows(seed_user_id)
        assert len(rows) == 1
        assert rows[0]["summary"].get("degraded") is True

    @pytest.mark.parametrize(
        "data",
        [
            {"preset": "bogus"},
            {"preset": "custom"},
            {"preset": "custom", "date_from": "2025-03-31", "date_to": "2025-03-01"},
            {"preset": "custom", "date_from": "2025-01-01", "date_to": "2999-01-01"},
            {"preset": "custom", "date_from": "x", "date_to": "y"},
        ],
    )
    def test_invalid_period_redirects_and_generates_nothing(
            self, auth_client, seed_user_id, ai_on, data):
        resp = auth_client.post("/insights/summary", data=data)
        assert resp.status_code == 302
        assert "/insights" in resp.headers["Location"]
        assert ai_on.calls == [], "No LLM call for an invalid period"
        assert _summary_rows(seed_user_id) == []

    def test_summary_rate_limit_returns_429(self, auth_client, seed_user_id, ai_on):
        for _ in range(5):
            _execute("INSERT INTO ai_usage (user_id, kind) VALUES (%s, 'summary')",
                     (seed_user_id,))
        resp = auth_client.post("/insights/summary",
                                data={"preset": "this_month", "force": "1"})
        assert resp.status_code == 429
        assert ai_on.calls == []

    def test_summary_usage_is_recorded(self, auth_client, seed_user_id, ai_on):
        auth_client.post("/insights/summary", data={"preset": "this_month"})
        rows = _query(
            "SELECT * FROM ai_usage WHERE user_id = %s AND kind = 'summary'",
            (seed_user_id,))
        assert len(rows) >= 1, "Summary generation should record ai_usage"

    def test_summaries_are_isolated_between_users(self, client, ai_on):
        user_a = _create_user("a@example.com", "A")
        user_b = _create_user("b@example.com", "B")
        _login(client, user_a)
        client.post("/insights/summary", data={"preset": "this_month"})
        assert len(_summary_rows(user_a)) == 1
        assert _summary_rows(user_b) == []
        # User B must not get A's cached narrative.
        _login(client, user_b)
        resp = client.get("/insights?preset=this_month")
        assert b"Your recorded activity is shown above." not in resp.data


# --------------------------------------------------------------------------
# POST /insights/chat
# --------------------------------------------------------------------------

@pytest.fixture
def chat_stub(monkeypatch):
    """Enable chat and stub the service call; records invocations."""
    import app as app_module
    calls = []

    def fake_run_chat(user_id, session_id, message, preset, date_from, date_to, **kw):
        calls.append({"user_id": user_id, "message": message, "preset": preset,
                      "date_from": date_from, "date_to": date_to})
        return {
            "session_id": "sess-1",
            "answer": "You spent a recorded amount.",
            "follow_up_suggestions": ["Compare with last month"],
            "period": {"preset": preset},
            "status": "ok",
            "degraded": False,
        }

    monkeypatch.setattr(app_module, "chat_enabled", lambda: True)
    monkeypatch.setattr(app_module, "run_chat", fake_run_chat)
    return calls


class TestChatRoute:
    def test_valid_message_returns_200_with_documented_shape(
            self, auth_client, chat_stub):
        resp = _chat_post(auth_client, {"message": "How is my budget?",
                                        "preset": "this_month"})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["answer"] == "You spent a recorded amount."
        assert body["follow_up_suggestions"] == ["Compare with last month"]
        assert "period" in body

    def test_user_id_comes_from_session_not_body(
            self, auth_client, seed_user_id, chat_stub):
        _chat_post(auth_client, {"message": "hi", "user_id": 99999})
        assert chat_stub[0]["user_id"] == seed_user_id

    def test_custom_period_is_forwarded(self, auth_client, chat_stub):
        resp = _chat_post(auth_client, {
            "message": "hi", "preset": "custom",
            "date_from": "2025-03-01", "date_to": "2025-03-31"})
        assert resp.status_code == 200
        assert chat_stub[0]["preset"] == "custom"
        assert chat_stub[0]["date_from"] == "2025-03-01"
        assert chat_stub[0]["date_to"] == "2025-03-31"

    def test_default_period_is_this_month(self, auth_client, chat_stub):
        _chat_post(auth_client, {"message": "hi"})
        assert chat_stub[0]["preset"] == "this_month"

    def test_message_of_500_chars_is_accepted(self, auth_client, chat_stub):
        resp = _chat_post(auth_client, {"message": "a" * 500})
        assert resp.status_code == 200

    @pytest.mark.parametrize(
        "message",
        ["", "   ", None, "a" * 501],
        ids=["empty", "whitespace", "null", "too_long"],
    )
    def test_invalid_message_returns_400(self, auth_client, chat_stub, message):
        resp = _chat_post(auth_client, {"message": message})
        assert resp.status_code == 400
        assert resp.is_json and "error" in resp.get_json()
        assert chat_stub == [], "Service must not be called for invalid input"

    def test_missing_message_key_returns_400(self, auth_client, chat_stub):
        assert _chat_post(auth_client, {"preset": "this_month"}).status_code == 400

    @pytest.mark.parametrize("payload", [["not", "a", "dict"], "just a string", 42])
    def test_non_object_json_returns_400(self, auth_client, chat_stub, payload):
        assert _chat_post(auth_client, payload).status_code == 400

    def test_malformed_json_returns_400(self, auth_client, chat_stub):
        resp = auth_client.post(
            "/insights/chat", data="{not json",
            content_type="application/json", headers={"Origin": LOCAL_ORIGIN})
        assert resp.status_code == 400

    def test_non_json_content_type_returns_400(self, auth_client, chat_stub):
        resp = auth_client.post(
            "/insights/chat", data={"message": "hi"},
            headers={"Origin": LOCAL_ORIGIN})
        assert resp.status_code == 400
        assert chat_stub == []

    @pytest.mark.parametrize(
        "extra",
        [
            {"preset": "bogus"},
            {"preset": "custom"},
            {"preset": "custom", "date_from": "2025-03-31", "date_to": "2025-03-01"},
            {"preset": "custom", "date_from": "2025-01-01", "date_to": "2999-01-01"},
            {"preset": "custom", "date_from": 123, "date_to": ["x"]},
        ],
    )
    def test_invalid_period_returns_400(self, auth_client, chat_stub, extra):
        resp = _chat_post(auth_client, {"message": "hi", **extra})
        assert resp.status_code == 400
        assert chat_stub == []

    @pytest.mark.parametrize("origin", [None, "http://evil.example.com"])
    def test_cross_origin_or_missing_origin_is_rejected(
            self, auth_client, chat_stub, origin):
        resp = _chat_post(auth_client, {"message": "hi"}, origin=origin)
        assert resp.status_code == 403
        assert chat_stub == []

    def test_referer_from_same_host_is_accepted(self, auth_client, chat_stub):
        resp = auth_client.post(
            "/insights/chat", json={"message": "hi"},
            headers={"Referer": "http://localhost/insights"})
        assert resp.status_code == 200

    def test_ai_disabled_returns_503(self, auth_client, ai_off):
        resp = _chat_post(auth_client, {"message": "How is my budget?"})
        assert resp.status_code == 503
        assert resp.is_json

    def test_ai_disabled_makes_no_llm_call(self, auth_client, ai_off):
        # ai_off raises AssertionError if a model is ever constructed.
        assert _chat_post(auth_client, {"message": "hi"}).status_code == 503

    def test_rate_limited_returns_429(self, auth_client, monkeypatch):
        import app as app_module
        monkeypatch.setattr(app_module, "chat_enabled", lambda: True)

        def limited(*a, **k):
            raise app_module.ChatRateLimit("Too many questions, slow down.")

        monkeypatch.setattr(app_module, "run_chat", limited)
        resp = _chat_post(auth_client, {"message": "hi"})
        assert resp.status_code == 429
        assert resp.is_json and resp.get_json().get("error")

    def test_per_minute_limit_enforced_from_usage_table(
            self, auth_client, seed_user_id, monkeypatch):
        import app as app_module
        import ai.service as service
        monkeypatch.setattr(app_module, "chat_enabled", lambda: True)
        monkeypatch.setattr(service, "chat_enabled", lambda: True)
        for _ in range(10):
            _execute("INSERT INTO ai_usage (user_id, kind) VALUES (%s, 'chat')",
                     (seed_user_id,))
        resp = _chat_post(auth_client, {"message": "How is my budget?"})
        assert resp.status_code == 429

    def test_chat_session_id_is_stored_server_side(self, auth_client, chat_stub):
        _chat_post(auth_client, {"message": "hi"})
        with auth_client.session_transaction() as sess:
            assert sess.get("ai_chat_session_id") == "sess-1"


# --------------------------------------------------------------------------
# POST /insights/chat/clear
# --------------------------------------------------------------------------

def _make_session_with_message(user_id, session_id):
    _execute("INSERT INTO ai_chat_sessions (id, user_id) VALUES (%s, %s)",
             (session_id, user_id))
    _execute(
        "INSERT INTO ai_chat_messages (session_id, user_id, role, content) "
        "VALUES (%s, %s, 'user', 'hello')", (session_id, user_id))


class TestChatClear:
    def _set_chat_session(self, client, session_id):
        with client.session_transaction() as sess:
            sess["ai_chat_session_id"] = session_id

    def test_json_clear_returns_204_and_deletes_history(
            self, auth_client, seed_user_id):
        _make_session_with_message(seed_user_id, "s-mine")
        self._set_chat_session(auth_client, "s-mine")
        resp = auth_client.post("/insights/chat/clear", json={},
                                headers={"Origin": LOCAL_ORIGIN})
        assert resp.status_code == 204
        assert _query("SELECT 1 FROM ai_chat_sessions WHERE id = 's-mine'") == []
        assert _query("SELECT 1 FROM ai_chat_messages WHERE session_id = 's-mine'") == []

    def test_form_clear_redirects_back_to_insights(self, auth_client, seed_user_id):
        _make_session_with_message(seed_user_id, "s-mine")
        self._set_chat_session(auth_client, "s-mine")
        resp = auth_client.post("/insights/chat/clear")
        assert resp.status_code == 302
        assert "/insights" in resp.headers["Location"]
        assert _query("SELECT 1 FROM ai_chat_sessions WHERE id = 's-mine'") == []

    def test_clear_without_existing_session_is_harmless(self, auth_client):
        resp = auth_client.post("/insights/chat/clear")
        assert resp.status_code == 302

    def test_json_clear_cross_origin_rejected(self, auth_client, seed_user_id):
        _make_session_with_message(seed_user_id, "s-mine")
        self._set_chat_session(auth_client, "s-mine")
        resp = auth_client.post("/insights/chat/clear", json={},
                                headers={"Origin": "http://evil.example.com"})
        assert resp.status_code == 403
        assert _query("SELECT 1 FROM ai_chat_sessions WHERE id = 's-mine'")

    def test_cannot_clear_another_users_session(self, auth_client):
        other = _create_user()
        _make_session_with_message(other, "s-theirs")
        self._set_chat_session(auth_client, "s-theirs")
        auth_client.post("/insights/chat/clear")
        assert _query("SELECT 1 FROM ai_chat_sessions WHERE id = 's-theirs'"), (
            "Another user's chat session must survive")
        assert _query("SELECT 1 FROM ai_chat_messages WHERE session_id = 's-theirs'")

    def test_cleared_history_not_rendered_on_page(self, auth_client, seed_user_id, ai_on):
        _make_session_with_message(seed_user_id, "s-mine")
        self._set_chat_session(auth_client, "s-mine")
        assert b"hello" in auth_client.get("/insights").data
        auth_client.post("/insights/chat/clear")
        assert b">hello<" not in auth_client.get("/insights").data


# --------------------------------------------------------------------------
# Account deletion removes AI data
# --------------------------------------------------------------------------

class TestDeleteUserRemovesAiData:
    def _seed_ai_rows(self, user_id):
        _execute(
            "INSERT INTO ai_summaries (user_id, period_preset, period_start, "
            "period_end, facts, summary, data_fingerprint, prompt_version, model) "
            "VALUES (%s, 'this_month', '2025-01-01', '2025-01-31', "
            "'{}'::jsonb, '{}'::jsonb, 'fp', 'v1', 'm')", (user_id,))
        _make_session_with_message(user_id, f"sess-{user_id}")
        _execute("INSERT INTO ai_usage (user_id, kind) VALUES (%s, 'chat')", (user_id,))

    def test_delete_user_query_removes_all_ai_rows_without_fk_error(self, seed_user_id):
        from database.queries import delete_user
        self._seed_ai_rows(seed_user_id)
        assert delete_user(seed_user_id) is True
        for table in ("ai_summaries", "ai_chat_sessions", "ai_chat_messages", "ai_usage"):
            rows = _query(f"SELECT 1 FROM {table} WHERE user_id = %s", (seed_user_id,))
            assert rows == [], f"{table} rows should be deleted with the user"
        assert _query("SELECT 1 FROM users WHERE id = %s", (seed_user_id,)) == []

    def test_delete_account_route_removes_ai_rows(self, auth_client, seed_user_id):
        self._seed_ai_rows(seed_user_id)
        resp = auth_client.post("/profile/delete")
        assert resp.status_code == 302
        assert _query("SELECT 1 FROM ai_summaries WHERE user_id = %s",
                      (seed_user_id,)) == []
        assert _query("SELECT 1 FROM users WHERE id = %s", (seed_user_id,)) == []

    def test_delete_user_leaves_other_users_ai_rows(self, seed_user_id):
        from database.queries import delete_user
        other = _create_user()
        self._seed_ai_rows(other)
        self._seed_ai_rows(seed_user_id)
        delete_user(seed_user_id)
        assert _query("SELECT 1 FROM ai_summaries WHERE user_id = %s", (other,))
        assert _query("SELECT 1 FROM ai_chat_messages WHERE user_id = %s", (other,))
        assert _query("SELECT 1 FROM ai_usage WHERE user_id = %s", (other,))
