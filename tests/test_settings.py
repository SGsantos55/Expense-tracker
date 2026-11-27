"""Tests for Step 1: Profile & Financial Settings."""
import pytest


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
    user = conn.execute("SELECT id FROM users WHERE email = %s", ("plankmax05@gmail.com",)).fetchone()
    conn.close()
    return user["id"] if user else None


@pytest.fixture
def auth_client(client, seed_user_id):
    """Test client logged in as seed user."""
    with client.session_transaction() as sess:
        sess["user_id"] = seed_user_id
    return client


# ------------------------------------------------------------------ #
# Access control                                                       #
# ------------------------------------------------------------------ #

class TestSettingsAccessControl:
    @pytest.mark.parametrize("path", [
        "/settings",
        "/settings/categories",
        "/settings/income",
        "/settings/budgets",
        "/settings/preferences",
    ])
    def test_anonymous_redirects_to_login(self, client, path):
        response = client.get(path)
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_logged_in_user_can_view_settings_home(self, auth_client):
        response = auth_client.get("/settings")
        assert response.status_code == 200
        assert b"Custom Categories" in response.data


# ------------------------------------------------------------------ #
# Categories                                                           #
# ------------------------------------------------------------------ #

class TestCategories:
    def test_create_expense_category(self, auth_client, seed_user_id):
        from database.settings_queries import get_categories

        response = auth_client.post("/settings/categories", data={
            "name": "Pet Care",
            "type": "expense",
            "icon": "paw-print",
            "color": "#00e58f",
        }, follow_redirects=True)

        assert response.status_code == 200
        categories = get_categories(seed_user_id, type="expense")
        assert any(c["name"] == "Pet Care" for c in categories)

    def test_duplicate_category_name_shows_error(self, auth_client):
        auth_client.post("/settings/categories", data={"name": "Pet Care", "type": "expense"})
        response = auth_client.post("/settings/categories", data={
            "name": "Pet Care", "type": "expense"
        }, follow_redirects=True)
        assert b"already exists" in response.data

    def test_invalid_category_name_rejected(self, auth_client, seed_user_id):
        from database.settings_queries import get_categories

        auth_client.post("/settings/categories", data={
            "name": "Bad!Name", "type": "expense"
        })
        categories = get_categories(seed_user_id, type="expense")
        assert not any(c["name"] == "Bad!Name" for c in categories)

    def test_edit_category(self, auth_client, seed_user_id):
        from database.settings_queries import get_categories, create_category

        category_id = create_category(seed_user_id, "Old Name", "expense")
        auth_client.post(f"/settings/categories/{category_id}/edit", data={
            "name": "New Name", "icon": "star", "color": "#123456"
        })
        categories = get_categories(seed_user_id, type="expense")
        updated = next(c for c in categories if c["id"] == category_id)
        assert updated["name"] == "New Name"
        assert updated["color"] == "#123456"

    def test_archive_and_restore_category(self, auth_client, seed_user_id):
        from database.settings_queries import get_categories, create_category

        category_id = create_category(seed_user_id, "Hobbies", "expense")
        auth_client.post(f"/settings/categories/{category_id}/archive", data={"archived": "1"})
        active = get_categories(seed_user_id, type="expense")
        assert not any(c["id"] == category_id for c in active)

        all_cats = get_categories(seed_user_id, type="expense", include_archived=True)
        assert next(c for c in all_cats if c["id"] == category_id)["is_archived"] is True

        auth_client.post(f"/settings/categories/{category_id}/archive", data={"archived": "0"})
        active_again = get_categories(seed_user_id, type="expense")
        assert any(c["id"] == category_id for c in active_again)

    def test_delete_unused_category(self, auth_client, seed_user_id):
        from database.settings_queries import get_categories, create_category

        category_id = create_category(seed_user_id, "Unused", "expense")
        auth_client.post(f"/settings/categories/{category_id}/delete")
        categories = get_categories(seed_user_id, type="expense", include_archived=True)
        assert not any(c["id"] == category_id for c in categories)

    def test_cannot_delete_category_in_use(self, auth_client, seed_user_id):
        from database.settings_queries import get_categories, create_category
        from database.queries import insert_expense

        category_id = create_category(seed_user_id, "Groceries", "expense")
        insert_expense(user_id=seed_user_id, amount=10.0, category="Groceries", date="2026-01-01")

        response = auth_client.post(f"/settings/categories/{category_id}/delete", follow_redirects=True)
        assert b"cannot be deleted" in response.data
        categories = get_categories(seed_user_id, type="expense", include_archived=True)
        assert any(c["id"] == category_id for c in categories)

    def test_custom_category_appears_in_add_expense_form(self, auth_client, seed_user_id):
        from database.settings_queries import create_category

        create_category(seed_user_id, "Pet Care", "expense")
        response = auth_client.get("/expenses/add")
        assert response.status_code == 200
        assert b"Pet Care" in response.data

    def test_archived_category_hidden_from_add_expense_form(self, auth_client, seed_user_id):
        from database.settings_queries import create_category

        category_id = create_category(seed_user_id, "Old Hobby", "expense")
        auth_client.post(f"/settings/categories/{category_id}/archive", data={"archived": "1"})
        response = auth_client.get("/expenses/add")
        assert response.status_code == 200
        assert b"Old Hobby" not in response.data


# ------------------------------------------------------------------ #
# Income                                                               #
# ------------------------------------------------------------------ #

class TestIncome:
    def test_add_income_entry(self, auth_client, seed_user_id):
        from database.settings_queries import get_income_entries

        response = auth_client.post("/settings/income", data={
            "source": "Salary",
            "amount": "3000",
            "effective_month": "2026-05",
        }, follow_redirects=True)

        assert response.status_code == 200
        entries = get_income_entries(seed_user_id)
        assert any(e["source"] == "Salary" and e["amount"] == 3000.0 for e in entries)

    def test_multiple_income_sources_same_month(self, auth_client, seed_user_id):
        from database.settings_queries import get_income_entries

        auth_client.post("/settings/income", data={
            "source": "Salary", "amount": "3000", "effective_month": "2026-05"
        })
        auth_client.post("/settings/income", data={
            "source": "Freelancing", "amount": "500", "effective_month": "2026-05"
        })

        entries = get_income_entries(seed_user_id)
        sources = {e["source"] for e in entries if e["effective_month"] == "2026-05"}
        assert sources == {"Salary", "Freelancing"}

    def test_invalid_amount_rejected(self, auth_client, seed_user_id):
        from database.settings_queries import get_income_entries

        auth_client.post("/settings/income", data={
            "source": "Salary", "amount": "not-a-number", "effective_month": "2026-05"
        })
        entries = get_income_entries(seed_user_id)
        assert len(entries) == 0

    def test_delete_income_entry(self, auth_client, seed_user_id):
        from database.settings_queries import add_income_entry, get_income_entries

        entry_id = add_income_entry(seed_user_id, "Business", 100.0, "2026-04")
        auth_client.post(f"/settings/income/{entry_id}/delete")
        entries = get_income_entries(seed_user_id)
        assert not any(e["id"] == entry_id for e in entries)


# ------------------------------------------------------------------ #
# Budgets                                                              #
# ------------------------------------------------------------------ #

class TestBudgets:
    def test_set_overall_budget(self, auth_client, seed_user_id):
        from database.settings_queries import get_budgets

        auth_client.post("/settings/budgets", data={"scope": "overall", "monthly_limit": "500"})
        budgets = get_budgets(seed_user_id)
        overall = next(b for b in budgets if b["category_id"] is None)
        assert overall["monthly_limit"] == 500.0

    def test_update_overall_budget_upserts(self, auth_client, seed_user_id):
        from database.settings_queries import get_budgets

        auth_client.post("/settings/budgets", data={"scope": "overall", "monthly_limit": "500"})
        auth_client.post("/settings/budgets", data={"scope": "overall", "monthly_limit": "750"})
        budgets = get_budgets(seed_user_id)
        overall_budgets = [b for b in budgets if b["category_id"] is None]
        assert len(overall_budgets) == 1
        assert overall_budgets[0]["monthly_limit"] == 750.0

    def test_set_category_budget_and_consumption(self, auth_client, seed_user_id):
        from database.settings_queries import create_category
        from database.queries import insert_expense
        from datetime import date

        category_id = create_category(seed_user_id, "Groceries", "expense")
        today = date.today().strftime("%Y-%m-%d")
        insert_expense(user_id=seed_user_id, amount=90.0, category="Groceries", date=today)

        auth_client.post("/settings/budgets", data={"scope": str(category_id), "monthly_limit": "100"})
        response = auth_client.get("/settings/budgets")
        assert response.status_code == 200
        assert b"90" in response.data

    def test_invalid_budget_amount_rejected(self, auth_client, seed_user_id):
        from database.settings_queries import get_budgets

        auth_client.post("/settings/budgets", data={"scope": "overall", "monthly_limit": "-5"})
        budgets = get_budgets(seed_user_id)
        assert not any(b["category_id"] is None for b in budgets)


# ------------------------------------------------------------------ #
# Preferences                                                          #
# ------------------------------------------------------------------ #

class TestPreferences:
    def test_default_preferences(self, auth_client):
        response = auth_client.get("/settings/preferences")
        assert response.status_code == 200
        assert b"USD" in response.data

    def test_update_preferences_persist(self, auth_client, seed_user_id):
        from database.settings_queries import get_user_preferences

        auth_client.post("/settings/preferences", data={
            "preferred_currency": "EUR",
            "financial_month_start_day": "15",
            "date_format": "DD/MM/YYYY",
            "number_format": "1.234,56",
            "default_export_format": "pdf",
        })

        prefs = get_user_preferences(seed_user_id)
        assert prefs["preferred_currency"] == "EUR"
        assert prefs["financial_month_start_day"] == 15
        assert prefs["date_format"] == "DD/MM/YYYY"
        assert prefs["number_format"] == "1.234,56"
        assert prefs["default_export_format"] == "pdf"

    def test_invalid_currency_rejected(self, auth_client, seed_user_id):
        from database.settings_queries import get_user_preferences

        auth_client.post("/settings/preferences", data={
            "preferred_currency": "ZZZ",
            "financial_month_start_day": "1",
            "date_format": "YYYY-MM-DD",
            "number_format": "1,234.56",
            "default_export_format": "xlsx",
        })

        prefs = get_user_preferences(seed_user_id)
        assert prefs["preferred_currency"] == "NPR"


# ------------------------------------------------------------------ #
# Account deletion (dependent rows removed)                            #
# ------------------------------------------------------------------ #

class TestDeleteAccount:
    def test_delete_account_removes_all_dependent_rows(self, auth_client, seed_user_id):
        from database.db import get_db
        from database.settings_queries import add_income_entry, set_overall_budget

        add_income_entry(seed_user_id, "Salary", 500.0, "2026-05")
        set_overall_budget(seed_user_id, 750.0)

        response = auth_client.post("/profile/delete")

        assert response.status_code == 302
        conn = get_db()
        try:
            assert conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE id = %s", (seed_user_id,)
            ).fetchone()["c"] == 0
            for table in ("expenses", "categories", "income_entries", "budgets"):
                assert conn.execute(
                    f"SELECT COUNT(*) AS c FROM {table} WHERE user_id = %s", (seed_user_id,)
                ).fetchone()["c"] == 0
        finally:
            conn.close()


class TestCategoryRenameCascade:
    def test_rename_updates_existing_expenses(self, auth_client, seed_user_id):
        from database.settings_queries import create_category, get_categories
        from database.queries import insert_expense, get_expense_by_id

        category_id = create_category(seed_user_id, "Groceries", "expense")
        expense_id = insert_expense(
            user_id=seed_user_id, amount=12.0, category="Groceries", date="2026-05-01"
        )

        auth_client.post(
            f"/settings/categories/{category_id}/edit",
            data={"name": "Snacks", "color": "#123456"},
        )

        expense = get_expense_by_id(expense_id, seed_user_id)
        assert expense["category"] == "Snacks"
        names = [c["name"] for c in get_categories(seed_user_id, type="expense", include_archived=True)]
        assert "Snacks" in names and "Groceries" not in names


class TestPreferenceFormatting:
    def test_date_and_number_format_apply_to_rendered_amounts(self, auth_client):
        auth_client.post("/settings/preferences", data={
            "preferred_currency": "NPR",
            "financial_month_start_day": "1",
            "date_format": "DD/MM/YYYY",
            "number_format": "1.234,56",
            "default_export_format": "xlsx",
        })

        response = auth_client.get("/profile")
        html = response.get_data(as_text=True)
        assert response.status_code == 200
        assert "02/05/2026" in html
        assert "45,50" in html
