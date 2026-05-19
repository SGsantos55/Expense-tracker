"""Tests for Step 7: Add Expense."""
import pytest
import time
from datetime import date


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
    from database.db import get_db
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


# ------------------------------------------------------------------ #
# Unit tests for insert_expense                                       #
# ------------------------------------------------------------------ #

class TestInsertExpense:
    def test_insert_expense_with_all_fields(self, app, seed_user_id):
        """insert_expense with valid data should insert a row and return its id."""
        from database.queries import insert_expense
        from database.db import get_db

        expense_id = insert_expense(
            user_id=seed_user_id,
            amount=50.0,
            category="Food",
            date="2026-03-20",
            description="Lunch"
        )

        assert expense_id is not None

        conn = get_db()
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        conn.close()

        assert row is not None
        assert row["user_id"] == seed_user_id
        assert row["amount"] == 50.0
        assert row["category"] == "Food"
        assert row["date"] == "2026-03-20"
        assert row["description"] == "Lunch"

    def test_insert_expense_with_none_description(self, app, seed_user_id):
        """insert_expense with description=None should store NULL in the DB."""
        from database.queries import insert_expense
        from database.db import get_db

        expense_id = insert_expense(
            user_id=seed_user_id,
            amount=25.50,
            category="Transport",
            date="2026-04-15",
            description=None
        )

        assert expense_id is not None

        conn = get_db()
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        conn.close()

        assert row is not None
        assert row["description"] is None


# ------------------------------------------------------------------ #
# Auth guard tests                                                     #
# ------------------------------------------------------------------ #

class TestAddExpenseAuthGuard:
    def test_get_unauthenticated_redirects_to_login(self, client):
        """GET /expenses/add for unauthenticated users should redirect to /login."""
        response = client.get("/expenses/add")
        assert response.status_code == 302
        assert "/login" in response.location

    def test_post_unauthenticated_redirects_to_login(self, client):
        """POST /expenses/add for unauthenticated users should redirect to /login."""
        response = client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        assert response.status_code == 302
        assert "/login" in response.location


# ------------------------------------------------------------------ #
# GET /expenses/add — authenticated                                   #
# ------------------------------------------------------------------ #

class TestGetAddExpenseAuthenticated:
    def test_returns_200(self, auth_client):
        """GET /expenses/add for authenticated users should return 200."""
        response = auth_client.get("/expenses/add")
        assert response.status_code == 200

    def test_contains_form_with_post_method(self, auth_client):
        """The page should contain a form with method POST."""
        response = auth_client.get("/expenses/add")
        html = response.get_data(as_text=True)
        assert "<form" in html
        assert 'method="POST"' in html or "method='POST'" in html

    def test_contains_category_select_with_all_seven_options(self, auth_client):
        """The category dropdown should contain all 7 fixed options."""
        response = auth_client.get("/expenses/add")
        html = response.get_data(as_text=True)
        assert "<select" in html
        assert "Food" in html
        assert "Transport" in html
        assert "Bills" in html
        assert "Health" in html
        assert "Entertainment" in html
        assert "Shopping" in html
        assert "Other" in html

    def test_contains_amount_input(self, auth_client):
        """The form should contain an amount number input."""
        response = auth_client.get("/expenses/add")
        html = response.get_data(as_text=True)
        assert 'type="number"' in html or 'name="amount"' in html

    def test_contains_date_input(self, auth_client):
        """The form should contain a date input."""
        response = auth_client.get("/expenses/add")
        html = response.get_data(as_text=True)
        assert 'type="date"' in html or 'name="date"' in html

    def test_contains_description_input(self, auth_client):
        """The form should contain a description input."""
        response = auth_client.get("/expenses/add")
        html = response.get_data(as_text=True)
        assert 'name="description"' in html

    def test_contains_submit_button(self, auth_client):
        """The form should contain a submit button."""
        response = auth_client.get("/expenses/add")
        html = response.get_data(as_text=True)
        assert 'type="submit"' in html or "<button" in html

    def test_contains_cancel_link_to_profile(self, auth_client):
        """The form should contain a cancel link back to /profile."""
        response = auth_client.get("/expenses/add")
        html = response.get_data(as_text=True)
        assert "/profile" in html

    def test_defaults_date_to_today(self, auth_client):
        """The date field should default to today's date (set via JS on page load)."""
        response = auth_client.get("/expenses/add")
        html = response.get_data(as_text=True)
        # The template sets today's date via JavaScript on DOMContentLoaded
        assert "toISOString" in html or "new Date()" in html or date.today().strftime("%Y-%m-%d") in html


# ------------------------------------------------------------------ #
# POST /expenses/add — valid data                                     #
# ------------------------------------------------------------------ #

class TestPostAddExpenseValidData:
    def test_valid_data_redirects_to_profile(self, auth_client):
        """POST with valid data should redirect to /profile."""
        response = auth_client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        assert response.status_code == 302
        assert "/profile" in response.location

    def test_valid_data_inserts_row_in_database(self, auth_client, seed_user_id):
        """POST with valid data should create a new expense row for the user."""
        from database.db import get_db

        before_count = get_db().execute(
            "SELECT COUNT(*) as count FROM expenses WHERE user_id = ?",
            (seed_user_id,)
        ).fetchone()["count"]

        auth_client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })

        after_count = get_db().execute(
            "SELECT COUNT(*) as count FROM expenses WHERE user_id = ?",
            (seed_user_id,)
        ).fetchone()["count"]

        assert after_count == before_count + 1

    def test_valid_data_stores_correct_values(self, auth_client, seed_user_id):
        """POST with valid data should store the correct values in the DB."""
        from database.db import get_db

        auth_client.post("/expenses/add", data={
            "amount": "75.25",
            "category": "Transport",
            "date": "2026-05-10",
            "description": "Taxi ride"
        })

        conn = get_db()
        row = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ? AND amount = ? AND category = ?",
            (seed_user_id, 75.25, "Transport")
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["date"] == "2026-05-10"
        assert row["description"] == "Taxi ride"

    def test_valid_data_shows_success_flash_message(self, auth_client):
        """POST with valid data should flash a success message."""
        response = auth_client.post("/expenses/add", data={
            "amount": "30.0",
            "category": "Bills",
            "date": "2026-04-01",
            "description": "Electric bill"
        }, follow_redirects=True)
        html = response.get_data(as_text=True)
        assert "Expense added successfully" in html or "success" in html.lower()


# ------------------------------------------------------------------ #
# POST /expenses/add — optional field: no description                 #
# ------------------------------------------------------------------ #

class TestPostAddExpenseNoDescription:
    def test_no_description_redirects_to_profile(self, auth_client):
        """POST with empty description should still redirect to /profile."""
        response = auth_client.post("/expenses/add", data={
            "amount": "20.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": ""
        })
        assert response.status_code == 302
        assert "/profile" in response.location

    def test_no_description_stores_null_in_database(self, auth_client, seed_user_id):
        """POST with empty description should store description as NULL."""
        from database.db import get_db

        auth_client.post("/expenses/add", data={
            "amount": "20.0",
            "category": "Food",
            "date": "2026-03-20",
            "description": ""
        })

        conn = get_db()
        row = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ? AND amount = ? ORDER BY id DESC LIMIT 1",
            (seed_user_id, 20.0)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["description"] is None

    def test_whitespace_only_description_stores_null(self, auth_client, seed_user_id):
        """POST with whitespace-only description should store description as NULL."""
        from database.db import get_db

        auth_client.post("/expenses/add", data={
            "amount": "15.0",
            "category": "Other",
            "date": "2026-03-20",
            "description": "   "
        })

        conn = get_db()
        row = conn.execute(
            "SELECT * FROM expenses WHERE user_id = ? AND amount = ? ORDER BY id DESC LIMIT 1",
            (seed_user_id, 15.0)
        ).fetchone()
        conn.close()

        assert row is not None
        assert row["description"] is None


# ------------------------------------------------------------------ #
# POST /expenses/add — validation: missing amount                     #
# ------------------------------------------------------------------ #

class TestPostAddExpenseMissingAmount:
    def test_missing_amount_returns_200(self, auth_client):
        """POST with missing amount should re-render the form (200)."""
        response = auth_client.post("/expenses/add", data={
            "amount": "",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        assert response.status_code == 200

    def test_missing_amount_shows_error_message(self, auth_client):
        """POST with missing amount should display an error message."""
        response = auth_client.post("/expenses/add", data={
            "amount": "",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        html = response.get_data(as_text=True)
        assert "error" in html.lower() or "required" in html.lower()

    def test_missing_amount_preserves_other_fields(self, auth_client):
        """POST with missing amount should preserve previously entered values."""
        response = auth_client.post("/expenses/add", data={
            "amount": "",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        html = response.get_data(as_text=True)
        assert "Food" in html
        assert "2026-03-20" in html
        assert "Lunch" in html

    def test_missing_amount_does_not_insert_row(self, auth_client, seed_user_id):
        """POST with missing amount should not insert a row."""
        from database.db import get_db

        before_count = get_db().execute(
            "SELECT COUNT(*) as count FROM expenses WHERE user_id = ?",
            (seed_user_id,)
        ).fetchone()["count"]

        auth_client.post("/expenses/add", data={
            "amount": "",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })

        after_count = get_db().execute(
            "SELECT COUNT(*) as count FROM expenses WHERE user_id = ?",
            (seed_user_id,)
        ).fetchone()["count"]

        assert after_count == before_count


# ------------------------------------------------------------------ #
# POST /expenses/add — validation: zero amount                        #
# ------------------------------------------------------------------ #

class TestPostAddExpenseZeroAmount:
    def test_zero_amount_returns_200(self, auth_client):
        """POST with amount=0 should re-render the form (200)."""
        response = auth_client.post("/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        assert response.status_code == 200

    def test_zero_amount_shows_error_message(self, auth_client):
        """POST with amount=0 should display an error message."""
        response = auth_client.post("/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        html = response.get_data(as_text=True)
        assert "error" in html.lower() or "greater" in html.lower() or "zero" in html.lower()

    def test_zero_amount_does_not_insert_row(self, auth_client, seed_user_id):
        """POST with amount=0 should not insert a row."""
        from database.db import get_db

        before_count = get_db().execute(
            "SELECT COUNT(*) as count FROM expenses WHERE user_id = ?",
            (seed_user_id,)
        ).fetchone()["count"]

        auth_client.post("/expenses/add", data={
            "amount": "0",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })

        after_count = get_db().execute(
            "SELECT COUNT(*) as count FROM expenses WHERE user_id = ?",
            (seed_user_id,)
        ).fetchone()["count"]

        assert after_count == before_count


# ------------------------------------------------------------------ #
# POST /expenses/add — validation: non-numeric amount                 #
# ------------------------------------------------------------------ #

class TestPostAddExpenseNonNumericAmount:
    def test_non_numeric_amount_returns_200(self, auth_client):
        """POST with non-numeric amount should re-render the form (200)."""
        response = auth_client.post("/expenses/add", data={
            "amount": "abc",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        assert response.status_code == 200

    def test_non_numeric_amount_shows_error_message(self, auth_client):
        """POST with non-numeric amount should display an error message."""
        response = auth_client.post("/expenses/add", data={
            "amount": "abc",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        html = response.get_data(as_text=True)
        assert "error" in html.lower() or "number" in html.lower() or "valid" in html.lower()

    def test_non_numeric_amount_does_not_insert_row(self, auth_client, seed_user_id):
        """POST with non-numeric amount should not insert a row."""
        from database.db import get_db

        before_count = get_db().execute(
            "SELECT COUNT(*) as count FROM expenses WHERE user_id = ?",
            (seed_user_id,)
        ).fetchone()["count"]

        auth_client.post("/expenses/add", data={
            "amount": "not-a-number",
            "category": "Food",
            "date": "2026-03-20",
            "description": "Lunch"
        })

        after_count = get_db().execute(
            "SELECT COUNT(*) as count FROM expenses WHERE user_id = ?",
            (seed_user_id,)
        ).fetchone()["count"]

        assert after_count == before_count


# ------------------------------------------------------------------ #
# POST /expenses/add — validation: invalid category                   #
# ------------------------------------------------------------------ #

class TestPostAddExpenseInvalidCategory:
    def test_invalid_category_returns_200(self, auth_client):
        """POST with an invalid category should re-render the form (200)."""
        response = auth_client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "InvalidCategory",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        assert response.status_code == 200

    def test_invalid_category_shows_error_message(self, auth_client):
        """POST with an invalid category should display an error message."""
        response = auth_client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "InvalidCategory",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        html = response.get_data(as_text=True)
        assert "error" in html.lower() or "valid" in html.lower() or "category" in html.lower()

    def test_invalid_category_does_not_insert_row(self, auth_client, seed_user_id):
        """POST with an invalid category should not insert a row."""
        from database.db import get_db

        before_count = get_db().execute(
            "SELECT COUNT(*) as count FROM expenses WHERE user_id = ?",
            (seed_user_id,)
        ).fetchone()["count"]

        auth_client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "InvalidCategory",
            "date": "2026-03-20",
            "description": "Lunch"
        })

        after_count = get_db().execute(
            "SELECT COUNT(*) as count FROM expenses WHERE user_id = ?",
            (seed_user_id,)
        ).fetchone()["count"]

        assert after_count == before_count

    def test_empty_category_returns_200(self, auth_client):
        """POST with empty category should re-render the form (200)."""
        response = auth_client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "",
            "date": "2026-03-20",
            "description": "Lunch"
        })
        assert response.status_code == 200


# ------------------------------------------------------------------ #
# POST /expenses/add — validation: invalid date                       #
# ------------------------------------------------------------------ #

class TestPostAddExpenseInvalidDate:
    def test_invalid_date_returns_200(self, auth_client):
        """POST with an invalid date should re-render the form (200)."""
        response = auth_client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "not-a-date",
            "description": "Lunch"
        })
        assert response.status_code == 200

    def test_invalid_date_shows_error_message(self, auth_client):
        """POST with an invalid date should display an error message."""
        response = auth_client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "not-a-date",
            "description": "Lunch"
        })
        html = response.get_data(as_text=True)
        assert "error" in html.lower() or "date" in html.lower() or "format" in html.lower()

    def test_invalid_date_does_not_insert_row(self, auth_client, seed_user_id):
        """POST with an invalid date should not insert a row."""
        from database.db import get_db

        before_count = get_db().execute(
            "SELECT COUNT(*) as count FROM expenses WHERE user_id = ?",
            (seed_user_id,)
        ).fetchone()["count"]

        auth_client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "not-a-date",
            "description": "Lunch"
        })

        after_count = get_db().execute(
            "SELECT COUNT(*) as count FROM expenses WHERE user_id = ?",
            (seed_user_id,)
        ).fetchone()["count"]

        assert after_count == before_count

    def test_empty_date_returns_200(self, auth_client):
        """POST with empty date should re-render the form (200)."""
        response = auth_client.post("/expenses/add", data={
            "amount": "50.0",
            "category": "Food",
            "date": "",
            "description": "Lunch"
        })
        assert response.status_code == 200


# ------------------------------------------------------------------ #
# POST /expenses/add — multiple validation errors                     #
# ------------------------------------------------------------------ #

class TestPostAddExpenseMultipleErrors:
    def test_multiple_invalid_fields_returns_200(self, auth_client):
        """POST with multiple invalid fields should re-render the form (200)."""
        response = auth_client.post("/expenses/add", data={
            "amount": "abc",
            "category": "InvalidCategory",
            "date": "bad-date",
            "description": ""
        })
        assert response.status_code == 200

    def test_multiple_invalid_fields_shows_errors(self, auth_client):
        """POST with multiple invalid fields should show error messages."""
        response = auth_client.post("/expenses/add", data={
            "amount": "abc",
            "category": "InvalidCategory",
            "date": "bad-date",
            "description": ""
        })
        html = response.get_data(as_text=True)
        assert "error" in html.lower()

    def test_multiple_invalid_fields_preserves_values(self, auth_client):
        """POST with multiple invalid fields should preserve previously entered values."""
        response = auth_client.post("/expenses/add", data={
            "amount": "abc",
            "category": "InvalidCategory",
            "date": "bad-date",
            "description": "Some description"
        })
        html = response.get_data(as_text=True)
        assert "abc" in html
        assert "bad-date" in html
        assert "Some description" in html


# ------------------------------------------------------------------ #
# POST /expenses/add — valid data for each valid category             #
# ------------------------------------------------------------------ #

class TestPostAddExpenseAllValidCategories:
    @pytest.mark.parametrize("category", [
        "Food", "Transport", "Bills", "Health",
        "Entertainment", "Shopping", "Other"
    ])
    def test_valid_category_redirects_to_profile(self, auth_client, category):
        """POST with each valid category should redirect to /profile."""
        response = auth_client.post("/expenses/add", data={
            "amount": "10.0",
            "category": category,
            "date": "2026-03-20",
            "description": f"Test {category}"
        })
        assert response.status_code == 302
        assert "/profile" in response.location
