from datetime import date

import pytest

import ai.service as service
from ai.config import AI_MODEL, AI_SUMMARY_PROMPT_VERSION
from ai.fingerprint import compute_data_fingerprint
from ai.graphs.summary_graph import run_summary_graph
from ai.llm import LLMUnavailable
from ai.periods import resolve_period
from ai.validation import build_fallback_summary, validate_summary
from database.ai_queries import (
    count_recent_usage,
    get_cached_summary,
    record_usage,
    save_summary,
)
from database.db import get_db
from database.settings_queries import get_user_preferences
from tests.ai_fakes import FakeChatModel, valid_summary_json

TODAY = date(2026, 6, 15)


@pytest.fixture()
def seed_user_id():
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE email = %s",
            ("plankmax05@gmail.com",),
        ).fetchone()
        return row["id"]
    finally:
        conn.close()


def _prefs(user_id):
    return get_user_preferences(user_id) or {}


def _period(user_id):
    return resolve_period("this_month", prefs=_prefs(user_id), today=TODAY)


def _summary_state(user_id, fake_model, force=True):
    from ai.analytics import build_facts

    prefs = _prefs(user_id)
    period = _period(user_id)
    facts = build_facts(user_id, period, prefs)
    fingerprint = compute_data_fingerprint(
        user_id, prefs, AI_SUMMARY_PROMPT_VERSION, AI_MODEL
    )
    return {
        "user_id": user_id,
        "preset": "this_month",
        "force": force,
        "prefs": prefs,
        "period": period,
        "facts": facts,
        "fingerprint": fingerprint,
        "model": AI_MODEL,
        "prompt_version": AI_SUMMARY_PROMPT_VERSION,
        "attempts": 0,
    }, fake_model


class TestFingerprintAndPersistence:
    def test_fingerprint_changes_when_expense_data_changes(self, seed_user_id):
        prefs = _prefs(seed_user_id)
        before = compute_data_fingerprint(
            seed_user_id, prefs, AI_SUMMARY_PROMPT_VERSION, AI_MODEL
        )

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date, description) "
                "VALUES (%s, %s, %s, %s, %s)",
                (seed_user_id, 42.5, "Food", "2026-06-10", "Fingerprint test"),
            )
            conn.commit()
        finally:
            conn.close()

        after = compute_data_fingerprint(
            seed_user_id, prefs, AI_SUMMARY_PROMPT_VERSION, AI_MODEL
        )
        assert before != after

    def test_summary_cache_round_trip(self, seed_user_id):
        period = _period(seed_user_id)
        fingerprint = compute_data_fingerprint(
            seed_user_id, _prefs(seed_user_id), AI_SUMMARY_PROMPT_VERSION, AI_MODEL
        )
        payload = {"overview": "Cached text", "key_findings": []}
        generated_at = save_summary(
            seed_user_id,
            period.preset,
            period.start.isoformat(),
            period.end.isoformat(),
            {"period": period.to_dict()},
            payload,
            fingerprint,
            AI_SUMMARY_PROMPT_VERSION,
            AI_MODEL,
        )

        cached = get_cached_summary(
            seed_user_id,
            period.start.isoformat(),
            period.end.isoformat(),
            AI_SUMMARY_PROMPT_VERSION,
            AI_MODEL,
            fingerprint,
        )
        assert cached is not None
        assert cached["summary"] == payload
        assert cached["generated_at"] == generated_at

    def test_usage_is_counted_by_kind(self, seed_user_id):
        assert count_recent_usage(seed_user_id, "summary", minutes=60) == 0
        record_usage(seed_user_id, "summary", AI_MODEL, 10, 20, 30)
        assert count_recent_usage(seed_user_id, "summary", minutes=60) == 1
        assert count_recent_usage(seed_user_id, "chat", minutes=60) == 0


class TestValidation:
    def test_accepts_grounded_summary(self, seed_user_id):
        state, _ = _summary_state(seed_user_id, FakeChatModel([]))
        summary = {
            "overview": "Your recorded activity is shown above.",
            "key_findings": [],
            "budget_analysis": "Your budget status is shown above.",
            "category_analysis": [],
            "recommendations": [],
            "warnings": [],
        }
        assert validate_summary(summary, state["facts"]) == []

    def test_rejects_invented_money_claim(self, seed_user_id):
        state, _ = _summary_state(seed_user_id, FakeChatModel([]))
        summary = {
            "overview": "You spent $999999 on unexpected things.",
            "key_findings": [],
            "budget_analysis": "Your budget status is shown above.",
            "category_analysis": [],
            "recommendations": [],
            "warnings": [],
        }
        errors = validate_summary(summary, state["facts"])
        assert any("monetary figure" in error for error in errors)

    def test_rejects_out_of_scope_advice(self, seed_user_id):
        state, _ = _summary_state(seed_user_id, FakeChatModel([]))
        summary = {
            "overview": "Based on your data, consider investing in stocks.",
            "key_findings": [],
            "budget_analysis": "Your budget status is shown above.",
            "category_analysis": [],
            "recommendations": [],
            "warnings": [],
        }
        errors = validate_summary(summary, state["facts"])
        assert any("outside recorded spending data" in error for error in errors)

    def test_rejects_unknown_recommendation(self, seed_user_id):
        state, _ = _summary_state(seed_user_id, FakeChatModel([]))
        summary = {
            "overview": "Your recorded activity is shown above.",
            "key_findings": [],
            "budget_analysis": "Your budget status is shown above.",
            "category_analysis": [],
            "recommendations": [
                {"insight_id": "not_a_real_insight", "text": "Consider reviewing this."}
            ],
            "warnings": [],
        }
        errors = validate_summary(summary, state["facts"])
        assert any("unknown insight" in error for error in errors)

    def test_fallback_summary_has_required_sections(self, seed_user_id):
        state, _ = _summary_state(seed_user_id, FakeChatModel([]))
        fallback = build_fallback_summary(state["facts"])
        assert fallback["overview"]
        assert fallback["budget_analysis"]
        assert isinstance(fallback["key_findings"], list)
        assert isinstance(fallback["recommendations"], list)


class TestSummaryGraph:
    def test_uses_cached_summary_without_calling_model(self, seed_user_id):
        state, fake = _summary_state(seed_user_id, FakeChatModel([]), force=False)
        save_summary(
            seed_user_id,
            state["period"].preset,
            state["period"].start.isoformat(),
            state["period"].end.isoformat(),
            state["facts"],
            {"overview": "Cached narrative", "key_findings": []},
            state["fingerprint"],
            AI_SUMMARY_PROMPT_VERSION,
            AI_MODEL,
        )

        result = run_summary_graph(state, model=fake)
        assert result["status"] == "cached"
        assert result["summary"]["overview"] == "Cached narrative"
        assert fake.calls == []

    def test_generates_and_persists_valid_summary(self, seed_user_id):
        state, fake = _summary_state(seed_user_id, FakeChatModel([valid_summary_json()]))

        result = run_summary_graph(state, model=fake)
        assert result["status"] == "generated"
        assert result["degraded"] is False
        assert len(fake.calls) == 1

        cached = get_cached_summary(
            seed_user_id,
            state["period"].start.isoformat(),
            state["period"].end.isoformat(),
            AI_SUMMARY_PROMPT_VERSION,
            AI_MODEL,
            state["fingerprint"],
        )
        assert cached is not None
        assert cached["summary"]["overview"] == "Your recorded activity is shown above."

    def test_retries_then_falls_back_on_parse_error(self, seed_user_id):
        state, fake = _summary_state(seed_user_id, FakeChatModel(["not json", "not json"]))

        result = run_summary_graph(state, model=fake)
        assert result["degraded"] is True
        assert result["status"] == "fallback"
        assert result["summary"]["overview"]
        assert len(fake.calls) == 2

    def test_provider_unavailable_falls_back(self, seed_user_id):
        state, fake = _summary_state(
            seed_user_id, FakeChatModel([LLMUnavailable("disabled")])
        )

        result = run_summary_graph(state, model=fake)
        assert result["degraded"] is True
        assert result["status"] == "disabled"
        assert result["summary"]["overview"]


class TestSummaryService:
    def test_build_page_context_does_not_call_graph(self, seed_user_id, monkeypatch):
        def blocked(*args, **kwargs):
            raise AssertionError("GET context must not call the graph")

        monkeypatch.setattr(service, "run_summary_graph", blocked)
        context = service.build_page_context(
            seed_user_id, "this_month", None, None, today=TODAY
        )
        assert context["facts"]["period"]["preset"] == "this_month"
        assert context["cached_summary"] is None

    def test_reuses_cached_summary(self, seed_user_id):
        period = _period(seed_user_id)
        prefs = _prefs(seed_user_id)
        fingerprint = compute_data_fingerprint(
            seed_user_id, prefs, AI_SUMMARY_PROMPT_VERSION, AI_MODEL
        )
        save_summary(
            seed_user_id,
            period.preset,
            period.start.isoformat(),
            period.end.isoformat(),
            {},
            {"overview": "Cached service summary"},
            fingerprint,
            AI_SUMMARY_PROMPT_VERSION,
            AI_MODEL,
        )
        fake = FakeChatModel([])

        result = service.generate_summary_for_user(
            seed_user_id, "this_month", None, None, model=fake, today=TODAY
        )
        assert result["status"] == "cached"
        assert result["summary"]["overview"] == "Cached service summary"
        assert fake.calls == []

    def test_force_regenerates_summary(self, seed_user_id):
        period = _period(seed_user_id)
        prefs = _prefs(seed_user_id)
        fingerprint = compute_data_fingerprint(
            seed_user_id, prefs, AI_SUMMARY_PROMPT_VERSION, AI_MODEL
        )
        save_summary(
            seed_user_id,
            period.preset,
            period.start.isoformat(),
            period.end.isoformat(),
            {},
            {"overview": "Old cached summary"},
            fingerprint,
            AI_SUMMARY_PROMPT_VERSION,
            AI_MODEL,
        )
        fake = FakeChatModel([valid_summary_json()])

        result = service.generate_summary_for_user(
            seed_user_id,
            "this_month",
            None,
            None,
            force=True,
            model=fake,
            today=TODAY,
        )
        assert result["status"] == "generated"
        assert result["summary"]["overview"] == "Your recorded activity is shown above."
        assert len(fake.calls) == 1

    def test_rate_limit_raises(self, seed_user_id, monkeypatch):
        monkeypatch.setattr(service, "AI_SUMMARY_LIMIT_PER_HOUR", 1)
        record_usage(seed_user_id, "summary", AI_MODEL)

        with pytest.raises(service.SummaryRateLimit):
            service.generate_summary_for_user(
                seed_user_id, "this_month", None, None, today=TODAY
            )
