"""Route-level tests for OAuth-only authentication."""
import pytest


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def fake_google(monkeypatch):
    """Patch the Google OAuth client so the callback receives a chosen userinfo."""
    import app as app_module

    def _set(userinfo=None, error=False):
        def fake_token():
            if error:
                raise RuntimeError("denied")
            return {"userinfo": userinfo}
        monkeypatch.setattr(app_module.oauth.google, "authorize_access_token", fake_token)
    return _set


def test_login_page_only_offers_google(client):
    html = client.get("/login").get_data(as_text=True)
    assert "Continue with Google" in html
    assert 'type="password"' not in html
    assert "Forgot password" not in html


def test_post_login_not_allowed(client):
    assert client.post("/login", data={"email": "a@b.co", "password": "x"}).status_code == 405


@pytest.mark.parametrize("method", ["get", "post"])
def test_register_redirects_to_login(client, method):
    response = getattr(client, method)("/register")
    assert response.status_code in (302, 308) or response.status_code == 405
    if method == "get":
        assert response.headers["Location"].endswith("/login")


@pytest.mark.parametrize("path", [
    "/verify/sometoken", "/password/forgot", "/password/reset/sometoken",
])
def test_removed_routes_404(client, path):
    assert client.get(path).status_code == 404
    assert client.post(path).status_code in (404, 405)


def test_callback_creates_verified_user(client, fake_google):
    from database.db import get_db
    fake_google({"sub": "g-new", "email": "New@Example.com", "name": "New User"})
    response = client.get("/login/google/callback")
    assert response.status_code == 302 and response.headers["Location"].endswith("/profile")
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id, email_verified, password_hash FROM users WHERE email = %s",
            ("new@example.com",),
        ).fetchone()
        cats = conn.execute(
            "SELECT COUNT(*) AS c FROM categories WHERE user_id = %s", (user["id"],)
        ).fetchone()["c"]
    finally:
        conn.close()
    assert user["email_verified"] == 1
    assert user["password_hash"] is None
    assert cats > 0


def test_callback_links_existing_user(client, fake_google):
    from database.db import get_db
    fake_google({"sub": "g-demo", "email": "plankmax05@gmail.com", "name": "Demo"})
    client.get("/login/google/callback")
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT google_id FROM users WHERE email = %s", ("plankmax05@gmail.com",)
        ).fetchall()
    finally:
        conn.close()
    assert [r["google_id"] for r in rows] == ["g-demo"]


def test_failed_callback_returns_to_login(client, fake_google):
    fake_google(error=True)
    response = client.get("/login/google/callback")
    assert response.status_code == 302 and response.headers["Location"].endswith("/login")


def test_seed_demo_user_has_no_password():
    from database.db import get_db
    conn = get_db()
    try:
        user = conn.execute("SELECT password_hash, email_verified FROM users").fetchone()
    finally:
        conn.close()
    assert user["password_hash"] is None and user["email_verified"] == 1
