"""Tests for Step 9: Delete Expense."""
import pytest
import time
from database.db import get_db

@pytest.fixture
def app():
    from app import app as flask_app
    flask_app.config.update({
        "TESTING": True,
        "SECRET_KEY": "test-secret",
    })
    return flask_app

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def seed_user_id(app):
    """Get the demo user ID from seed data."""
    conn = get_db()
    user = conn.execute("SELECT id FROM users WHERE email = ?", ("demo@spendly.com",)).fetchone()
    conn.close()
    return user["id"] if user else None

@pytest.fixture
def auth_client(client, seed_user_id):
    """Test client logged in as seed user."""
    with client.session_transaction() as sess:
        sess["user_id"] = seed_user_id
    return client

@pytest.fixture
def seed_expense_id(app, seed_user_id):
    """Get the first expense ID belonging to the seed user."""
    conn = get_db()
    expense = conn.execute(
        "SELECT id FROM expenses WHERE user_id = ? ORDER BY id LIMIT 1",
        (seed_user_id,)
    ).fetchone()
    conn.close()
    return expense["id"] if expense else None

# ------------------------------------------------------------------ #
# Unit tests for delete_expense                                       #
# ------------------------------------------------------------------ #

class TestDeleteExpenseUnit:
    def test_valid_delete_removes_row(self, seed_user_id, seed_expense_id):
        """delete_expense with valid id and correct user_id should remove the row."""
        from database.queries import delete_expense

        result = delete_expense(seed_expense_id, seed_user_id)
        assert result is True

        conn = get_db()
        row = conn.execute("SELECT id FROM expenses WHERE id = ?", (seed_expense_id,)).fetchone()
        conn.close()
        assert row is None

    def test_wrong_user_id_does_not_delete(self, seed_expense_id):
        """delete_expense with valid id but wrong user_id should not remove the row."""
        from database.queries import delete_expense

        wrong_user_id = -1
        result = delete_expense(seed_expense_id, wrong_user_id)
        assert result is False

        conn = get_db()
        row = conn.execute("SELECT id FROM expenses WHERE id = ?", (seed_expense_id,)).fetchone()
        conn.close()
        assert row is not None

    def test_non_existent_id_does_not_error(self, seed_user_id):
        """delete_expense with non-existent id should not raise error and return False."""
        from database.queries import delete_expense

        result = delete_expense(-999, seed_user_id)
        assert result is False

# ------------------------------------------------------------------ #
# Route tests for POST /expenses/<id>/delete                            #
# ------------------------------------------------------------------ #

class TestDeleteExpenseRoute:
    def test_unauthenticated_redirects_to_login(self, client):
        """POST /expenses/<id>/delete for unauthenticated users should redirect to /login."""
        response = client.post("/expenses/1/delete")
        assert response.status_code == 302
        assert "/login" in response.location

    def test_own_expense_redirects_to_profile(self, auth_client, seed_expense_id):
        """POST with own expense should redirect to /profile and remove the expense."""
        response = auth_client.post(f"/expenses/{seed_expense_id}/delete")
        assert response.status_code == 302
        assert "/profile" in response.location

        conn = get_db()
        row = conn.execute("SELECT id FROM expenses WHERE id = ?", (seed_expense_id,)).fetchone()
        conn.close()
        assert row is None

    def test_other_user_expense_returns_404(self, auth_client):
        """POST to another user's expense should return 404."""
        conn = get_db()
        try:
            cursor = conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                ("Other User", f"other_user_{time.time_ns()}@test.com", "hash")
            )
            other_user_id = cursor.lastrowid
            cursor = conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
                (other_user_id, 20.0, "Transport", "2026-02-01", "Other expense")
            )
            other_expense_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()

        response = auth_client.post(f"/expenses/{other_expense_id}/delete")
        assert response.status_code == 404

    def test_non_existent_id_returns_404(self, auth_client):
        """POST with non-existent id should return 404."""
        response = auth_client.post("/expenses/-999/delete")
        assert response.status_code == 404

    def test_get_request_returns_405(self, auth_client, seed_expense_id):
        """GET /expenses/<id>/delete should return 405 Method Not Allowed."""
        response = auth_client.get(f"/expenses/{seed_expense_id}/delete")
        assert response.status_code == 405
