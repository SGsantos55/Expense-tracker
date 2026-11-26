import pytest


@pytest.fixture()
def app():
    from app import app as flask_app

    flask_app.config.update({"TESTING": True, "SECRET_KEY": "test-secret"})
    return flask_app


@pytest.fixture()
def client(app):
    test_client = app.test_client()
    test_client.environ_base["HTTP_ORIGIN"] = "http://localhost"
    return test_client


@pytest.fixture()
def seed_user_id():
    from database.db import get_db

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE email = %s",
            ("plankmax05@gmail.com",),
        ).fetchone()
        return row["id"]
    finally:
        conn.close()


@pytest.fixture()
def auth_client(client, seed_user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = seed_user_id
    return client


class TestInsightsAccessControl:
    @pytest.mark.parametrize("path", ["/insights", "/insights/summary"])
    def test_anonymous_user_redirects_to_login(self, client, path):
        response = client.get(path) if path == "/insights" else client.post(path)
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


class TestInsightsPage:
    def test_logged_in_user_sees_deterministic_insights(self, auth_client, monkeypatch):
        import ai.service as service

        def blocked(*args, **kwargs):
            raise AssertionError("GET /insights must not call the LLM graph")

        monkeypatch.setattr(service, "run_summary_graph", blocked)
        response = auth_client.get("/insights")

        assert response.status_code == 200
        assert b"Rule-based insights" in response.data
        assert b"Category breakdown" in response.data
        assert b"Generate summary" in response.data

    def test_invalid_period_falls_back_with_notice(self, auth_client):
        response = auth_client.get("/insights?preset=not-a-preset", follow_redirects=True)
        assert response.status_code == 200
        assert b"Using this month instead" in response.data

    def test_nav_and_privacy_disclose_insights(self, auth_client):
        response = auth_client.get("/insights")
        assert b'href="/insights"' in response.data

        privacy = auth_client.get("/privacy")
        assert b"AI Insights" in privacy.data
        assert b"Raw expense descriptions" in privacy.data
        assert b"limited set of matching expense rows" in privacy.data
        assert b"provider to train on submitted content" in privacy.data
        assert b"provider API key stays on our server" in privacy.data


class TestSummaryRoute:
    def test_post_generates_summary_and_redirects(self, auth_client, monkeypatch):
        import app as app_module

        def fake_generate(*args, **kwargs):
            return {
                "status": "generated",
                "degraded": False,
                "rate_limited": False,
                "period_params": {"preset": "this_month"},
                "summary": {"overview": "Generated"},
            }

        monkeypatch.setattr(app_module, "generate_summary_for_user", fake_generate)
        response = auth_client.post(
            "/insights/summary",
            data={"preset": "this_month"},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"AI summary generated." in response.data

    def test_post_rate_limit_returns_429(self, auth_client, monkeypatch):
        import app as app_module

        def too_many(*args, **kwargs):
            raise app_module.SummaryRateLimit("limit")

        monkeypatch.setattr(app_module, "generate_summary_for_user", too_many)
        response = auth_client.post("/insights/summary", data={"preset": "this_month"})
        assert response.status_code == 429

    def test_invalid_period_redirects_without_generating(self, auth_client, monkeypatch):
        import app as app_module

        def blocked(*args, **kwargs):
            raise AssertionError("Invalid period must not generate a summary")

        monkeypatch.setattr(app_module, "generate_summary_for_user", blocked)
        response = auth_client.post(
            "/insights/summary",
            data={"preset": "custom", "date_from": "2026-06-30", "date_to": "2026-06-01"},
        )
        assert response.status_code == 302
        assert "/insights" in response.headers["Location"]
