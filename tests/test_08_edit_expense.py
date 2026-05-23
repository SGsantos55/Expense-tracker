"""Tests for Step 8: Edit Expense."""
import pytest
import time
from datetime import date

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
# Unit tests for get_expense_by_id                                    #
# ------------------------------------------------------------------ #


class TestGetExpenseById:
    def test_valid_expense_id_returns_expense(self, seed_user_id, seed_expense_id):
        """get_expense_by_id with valid id and correct user_id should return the expense."""
        from database.queries import get_expense_by_id

        expense = get_expense_by_id(seed_expense_id, seed_user_id)
        assert expense is not None
        assert expense["id"] == seed_expense_id

    def test_wrong_user_id_returns_none(self, seed_expense_id):
        """get_expense_by_id with valid id but wrong user_id should return None."""
        from database.queries import get_expense_by_id

        wrong_user_id = -1
        expense = get_expense_by_id(seed_expense_id, wrong_user_id)
        assert expense is None

    def test_non_existent_id_returns_none(self, seed_user_id):
        """get_expense_by_id with non-existent id should return None."""
        from database.queries import get_expense_by_id

        expense = get_expense_by_id(-999, seed_user_id)
        assert expense is None


# ------------------------------------------------------------------ #
# Unit tests for update_expense                                       #
# ------------------------------------------------------------------ #


class TestUpdateExpense:
    def test_valid_update_changes_row(self, seed_user_id, seed_expense_id):
        """update_expense with valid id and correct user_id should update the row."""
        from database.queries import update_expense
        from database.db import get_db

        updated = update_expense(
            expense_id=seed_expense_id,
            user_id=seed_user_id,
            amount=99.0,
            category="Transport",
            date="2026-06-01",
            description="Updated expense"
        )
        assert updated is True

        conn = get_db()
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (seed_expense_id,)).fetchone()
        conn.close()
        assert row["amount"] == 99.0
        assert row["category"] == "Transport"
        assert row["date"] == "2026-06-01"
        assert row["description"] == "Updated expense"

    def test_wrong_user_id_does_not_update(self, seed_expense_id):
        """update_expense with valid id but wrong user_id should not change the row."""
        from database.queries import update_expense
        from database.db import get_db

        conn = get_db()
        original = conn.execute(
            "SELECT amount, category, date, description FROM expenses WHERE id = ?",
            (seed_expense_id,)
        ).fetchone()
        conn.close()

        wrong_user_id = -1
        result = update_expense(
            expense_id=seed_expense_id,
            user_id=wrong_user_id,
            amount=999.0,
            category="Shopping",
            date="2026-12-31",
            description="Should not update"
        )

        assert result is False

        conn = get_db()
        row = conn.execute(
            "SELECT amount, category, date, description FROM expenses WHERE id = ?",
            (seed_expense_id,)
        ).fetchone()
        conn.close()

        assert row["amount"] == original["amount"]
        assert row["category"] == original["category"]
        assert row["date"] == original["date"]
        assert row["description"] == original["description"]


# ------------------------------------------------------------------ #
# Auth guard tests                                                     #
# ------------------------------------------------------------------ #


class TestEditExpenseAuthGuard:
    def test_get_unauthenticated_redirects_to_login(self, client):
        """GET /expenses/<id>/edit for unauthenticated users should redirect to /login."""
        response = client.get("/expenses/1/edit")
        assert response.status_code == 302
        assert "/login" in response.location

    def test_post_unauthenticated_redirects_to_login(self, client):
        """POST /expenses/<id>/edit for unauthenticated users should redirect to /login."""
        response = client.post("/expenses/1/edit", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        assert response.status_code == 302
        assert "/login" in response.location


# ------------------------------------------------------------------ #
# GET /expenses/<id>/edit — authenticated                             #
# ------------------------------------------------------------------ #


class TestGetEditExpenseAuthenticated:
    def test_own_expense_returns_200(self, auth_client, seed_expense_id):
        """GET with own expense should return 200."""
        response = auth_client.get(f"/expenses/{seed_expense_id}/edit")
        assert response.status_code == 200

    def test_own_expense_shows_form(self, auth_client, seed_expense_id):
        """GET with own expense should contain a form."""
        response = auth_client.get(f"/expenses/{seed_expense_id}/edit")
        html = response.get_data(as_text=True)
        assert "<form" in html
        assert 'method="POST"' in html or "method='POST'" in html

    def test_own_expense_prefilled_amount(self, auth_client, seed_expense_id):
        """GET with own expense should pre-fill the amount field."""
        from database.db import get_db
        conn = get_db()
        expense = conn.execute("SELECT * FROM expenses WHERE id = ?", (seed_expense_id,)).fetchone()
        conn.close()

        response = auth_client.get(f"/expenses/{seed_expense_id}/edit")
        html = response.get_data(as_text=True)
        assert str(expense["amount"]) in html

    def test_own_expense_prefilled_date(self, auth_client, seed_expense_id):
        """GET with own expense should pre-fill the date field."""
        from database.db import get_db
        conn = get_db()
        expense = conn.execute("SELECT * FROM expenses WHERE id = ?", (seed_expense_id,)).fetchone()
        conn.close()

        response = auth_client.get(f"/expenses/{seed_expense_id}/edit")
        html = response.get_data(as_text=True)
        assert expense["date"] in html

    def test_own_expense_prefilled_category(self, auth_client, seed_expense_id):
        """GET with own expense should pre-select the category."""
        from database.db import get_db
        conn = get_db()
        expense = conn.execute("SELECT * FROM expenses WHERE id = ?", (seed_expense_id,)).fetchone()
        conn.close()

        response = auth_client.get(f"/expenses/{seed_expense_id}/edit")
        html = response.get_data(as_text=True)
        assert expense["category"] in html

    def test_own_expense_prefilled_description(self, auth_client, seed_expense_id):
        """GET with own expense should pre-fill the description field."""
        from database.db import get_db
        conn = get_db()
        expense = conn.execute("SELECT * FROM expenses WHERE id = ?", (seed_expense_id,)).fetchone()
        conn.close()

        response = auth_client.get(f"/expenses/{seed_expense_id}/edit")
        html = response.get_data(as_text=True)
        if expense["description"]:
            assert expense["description"] in html

    def test_own_expense_contains_submit_button(self, auth_client, seed_expense_id):
        """GET with own expense should contain a submit button."""
        response = auth_client.get(f"/expenses/{seed_expense_id}/edit")
        html = response.get_data(as_text=True)
        assert 'type="submit"' in html or "Update Expense" in html or "Save Changes" in html

    def test_own_expense_contains_cancel_link(self, auth_client, seed_expense_id):
        """GET with own expense should contain a cancel link to /profile."""
        response = auth_client.get(f"/expenses/{seed_expense_id}/edit")
        html = response.get_data(as_text=True)
        assert "/profile" in html

    def test_other_user_expense_returns_404(self, auth_client):
        """GET with another user's expense should return 404."""
        conn = get_db()
        try:
            cursor = conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                ("Other User", f"other_user_{time.time_ns()}@test.com", "hash")
            )
            other_user_id = cursor.lastrowid
            cursor = conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)",
                (other_user_id, 10.0, "Food", "2026-01-01", "Other user expense")
            )
            other_expense_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()

        response = auth_client.get(f"/expenses/{other_expense_id}/edit")
        assert response.status_code == 404

    def test_non_existent_id_returns_404(self, auth_client):
        """GET with non-existent id should return 404."""
        response = auth_client.get("/expenses/-999/edit")
        assert response.status_code == 404


# ------------------------------------------------------------------ #
# POST /expenses/<id>/edit — valid data                               #
# ------------------------------------------------------------------ #


class TestPostEditExpenseValidData:
    def test_valid_data_redirects_to_profile(self, auth_client, seed_expense_id):
        """POST with valid data should redirect to /profile."""
        response = auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "99.99",
            "category": "Health",
            "date": "2026-07-15",
            "description": "Doctor visit"
        })
        assert response.status_code == 302
        assert "/profile" in response.location

    def test_valid_data_updates_database(self, auth_client, seed_expense_id):
        """POST with valid data should update the row in the database."""
        auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "55.50",
            "category": "Bills",
            "date": "2026-08-01",
            "description": "Electricity bill"
        })

        conn = get_db()
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (seed_expense_id,)).fetchone()
        conn.close()

        assert row["amount"] == 55.50
        assert row["category"] == "Bills"
        assert row["date"] == "2026-08-01"
        assert row["description"] == "Electricity bill"

    def test_other_user_expense_post_returns_404(self, auth_client):
        """POST to another user's expense should return 404."""
        conn = get_db()
        try:
            cursor = conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                ("Other User 2", f"other_user_2_{time.time_ns()}@test.com", "hash")
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

        response = auth_client.post(f"/expenses/{other_expense_id}/edit", data={
            "amount": "99.0",
            "category": "Food",
            "date": "2026-03-01",
            "description": "Hacked"
        })
        assert response.status_code == 404


# ------------------------------------------------------------------ #
# POST /expenses/<id>/edit — validation: missing amount               #
# ------------------------------------------------------------------ #


class TestPostEditExpenseMissingAmount:
    def test_missing_amount_returns_200(self, auth_client, seed_expense_id):
        """POST with missing amount should re-render the form (200)."""
        response = auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        assert response.status_code == 200

    def test_missing_amount_shows_error_message(self, auth_client, seed_expense_id):
        """POST with missing amount should display an error message."""
        response = auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        html = response.get_data(as_text=True)
        assert "error" in html.lower() or "required" in html.lower()

    def test_missing_amount_does_not_update(self, auth_client, seed_expense_id):
        """POST with missing amount should not update the row."""
        from database.db import get_db

        conn = get_db()
        original = conn.execute(
            "SELECT amount, category, date, description FROM expenses WHERE id = ?",
            (seed_expense_id,)
        ).fetchone()
        conn.close()

        auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })

        conn = get_db()
        row = conn.execute(
            "SELECT amount, category, date, description FROM expenses WHERE id = ?",
            (seed_expense_id,)
        ).fetchone()
        conn.close()

        assert row["amount"] == original["amount"]
        assert row["category"] == original["category"]
        assert row["date"] == original["date"]

    def test_missing_amount_preserves_submitted_values(self, auth_client, seed_expense_id):
        """POST with missing amount should preserve submitted values in the form."""
        response = auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "",
            "category": "Food",
            "date": "2026-05-15",
            "description": "Pizza night"
        })
        html = response.get_data(as_text=True)
        assert "Food" in html
        assert "2026-05-15" in html
        assert "Pizza night" in html


# ------------------------------------------------------------------ #
# POST /expenses/<id>/edit — validation: zero amount                  #
# ------------------------------------------------------------------ #


class TestPostEditExpenseZeroAmount:
    def test_zero_amount_returns_200(self, auth_client, seed_expense_id):
        """POST with amount=0 should re-render the form (200)."""
        response = auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        assert response.status_code == 200

    def test_zero_amount_shows_error_message(self, auth_client, seed_expense_id):
        """POST with amount=0 should display an error message."""
        response = auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        html = response.get_data(as_text=True)
        assert "error" in html.lower() or "greater" in html.lower() or "zero" in html.lower()


# ------------------------------------------------------------------ #
# POST /expenses/<id>/edit — validation: non-numeric amount           #
# ------------------------------------------------------------------ #


class TestPostEditExpenseNonNumericAmount:
    def test_non_numeric_amount_returns_200(self, auth_client, seed_expense_id):
        """POST with non-numeric amount should re-render the form (200)."""
        response = auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "abc",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        assert response.status_code == 200

    def test_non_numeric_amount_shows_error_message(self, auth_client, seed_expense_id):
        """POST with non-numeric amount should display an error message."""
        response = auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "abc",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        html = response.get_data(as_text=True)
        assert "error" in html.lower() or "number" in html.lower() or "valid" in html.lower()


# ------------------------------------------------------------------ #
# POST /expenses/<id>/edit — validation: invalid category             #
# ------------------------------------------------------------------ #


class TestPostEditExpenseInvalidCategory:
    def test_invalid_category_returns_200(self, auth_client, seed_expense_id):
        """POST with an invalid category should re-render the form (200)."""
        response = auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "50.0",
            "category": "InvalidCategory",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        assert response.status_code == 200

    def test_invalid_category_shows_error_message(self, auth_client, seed_expense_id):
        """POST with an invalid category should display an error message."""
        response = auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "50.0",
            "category": "InvalidCategory",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        html = response.get_data(as_text=True)
        assert "error" in html.lower() or "valid" in html.lower() or "category" in html.lower()


# ------------------------------------------------------------------ #
# POST /expenses/<id>/edit — validation: invalid date                 #
# ------------------------------------------------------------------ #


class TestPostEditExpenseInvalidDate:
    def test_invalid_date_returns_200(self, auth_client, seed_expense_id):
        """POST with an invalid date should re-render the form (200)."""
        response = auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "50.0",
            "category": "Food",
            "date": "not-a-date",
            "description": "Lunch"
        })
        assert response.status_code == 200

    def test_invalid_date_shows_error_message(self, auth_client, seed_expense_id):
        """POST with an invalid date should display an error message."""
        response = auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "50.0",
            "category": "Food",
            "date": "not-a-date",
            "description": "Lunch"
        })
        html = response.get_data(as_text=True)
        assert "error" in html.lower() or "date" in html.lower() or "format" in html.lower()


# ------------------------------------------------------------------ #
# POST /expenses/<id>/edit — no description                           #
# ------------------------------------------------------------------ #


class TestPostEditExpenseNoDescription:
    def test_no_description_redirects_to_profile(self, auth_client, seed_expense_id):
        """POST with empty description should redirect to /profile."""
        response = auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "30.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": ""
        })
        assert response.status_code == 302
        assert "/profile" in response.location

    def test_no_description_stores_null(self, auth_client, seed_expense_id):
        """POST with empty description should store NULL in the database."""
        auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "30.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": ""
        })

        conn = get_db()
        row = conn.execute("SELECT description FROM expenses WHERE id = ?", (seed_expense_id,)).fetchone()
        conn.close()

        assert row["description"] is None

    def test_whitespace_only_description_stores_null(self, auth_client, seed_expense_id):
        """POST with whitespace-only description should store NULL."""
        auth_client.post(f"/expenses/{seed_expense_id}/edit", data={
            "amount": "30.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "   "
        })

        conn = get_db()
        row = conn.execute("SELECT description FROM expenses WHERE id = ?", (seed_expense_id,)).fetchone()
        conn.close()

        assert row["description"] is None
