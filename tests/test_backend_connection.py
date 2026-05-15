"""Tests for backend connection: query functions and /profile route."""
import pytest
from datetime import datetime


@pytest.fixture
def app():
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seed_user_id(app):
    from database.db import get_db
    conn = get_db()
    user = conn.execute("SELECT id FROM users WHERE email = ?", ("demo@spendly.com",)).fetchone()
    conn.close()
    return user["id"] if user else None


@pytest.fixture
def auth_client(client, seed_user_id, app):
    """Test client logged in as seed user."""
    with client.session_transaction() as sess:
        sess["user_id"] = seed_user_id
    return client


# ------------------------------------------------------------------ #
# Query function tests                                                #
# ------------------------------------------------------------------ #

class TestGetUserById:
    def test_returns_correct_user_data(self, seed_user_id):
        from database.queries import get_user_by_id
        result = get_user_by_id(seed_user_id)
        assert result["name"] == "Demo User"
        assert result["email"] == "demo@spendly.com"
        assert "member_since" in result

    def test_returns_none_for_nonexistent_id(self):
        from database.queries import get_user_by_id
        result = get_user_by_id(99999)
        assert result is None


class TestGetSummaryStats:
    def test_returns_correct_stats(self, seed_user_id):
        from database.queries import get_summary_stats
        stats = get_summary_stats(seed_user_id)
        assert stats["total_spent"] > 0
        assert stats["transaction_count"] == 8
        assert stats["top_category"] == "Bills"

    def test_returns_zeros_for_user_with_no_expenses(self, app):
        from database.db import get_db
        from database.queries import get_summary_stats
        import time
        # Create new user without expenses (unique email to avoid conflicts)
        conn = get_db()
        email = f"noexpenses{int(time.time())}@test.com"
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("No Expenses User", email, "dummyhash")
        )
        conn.commit()
        new_user_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
        conn.close()

        stats = get_summary_stats(new_user_id)
        assert stats["total_spent"] == 0
        assert stats["transaction_count"] == 0
        assert stats["top_category"] == "—"


class TestGetRecentTransactions:
    def test_returns_transactions_newest_first(self, seed_user_id):
        from database.queries import get_recent_transactions
        transactions = get_recent_transactions(seed_user_id)
        assert len(transactions) == 8
        # Verify newest first
        for i in range(len(transactions) - 1):
            assert transactions[i]["date"] >= transactions[i + 1]["date"]

    def test_returns_empty_for_user_with_no_expenses(self, seed_user_id):
        from database.db import get_db
        from database.queries import get_recent_transactions
        import time
        # Create new user without expenses
        conn = get_db()
        email = f"empty{int(time.time())}@test.com"
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Empty User", email, "dummyhash")
        )
        conn.commit()
        new_user_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
        conn.close()

        transactions = get_recent_transactions(new_user_id)
        assert transactions == []


class TestGetCategoryBreakdown:
    def test_returns_categories_with_percentages(self, seed_user_id):
        from database.queries import get_category_breakdown
        categories = get_category_breakdown(seed_user_id)
        assert len(categories) == 7
        pct_sum = sum(c["pct"] for c in categories)
        assert pct_sum == 100
        # Verify ordered by amount descending
        for i in range(len(categories) - 1):
            assert categories[i]["amount"] >= categories[i + 1]["amount"]

    def test_returns_empty_for_user_with_no_expenses(self, seed_user_id):
        from database.db import get_db
        from database.queries import get_category_breakdown
        import time
        # Create new user without expenses
        conn = get_db()
        email = f"emptycat{int(time.time())}@test.com"
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Empty Cat User", email, "dummyhash")
        )
        conn.commit()
        new_user_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
        conn.close()

        categories = get_category_breakdown(new_user_id)
        assert categories == []


# ------------------------------------------------------------------ #
# Route tests                                                         #
# ------------------------------------------------------------------ #

class TestProfileRoute:
    def test_unauthenticated_redirects_to_login(self, client):
        response = client.get("/profile")
        assert response.status_code == 302
        assert "/login" in response.location

    def test_authenticated_returns_200(self, auth_client):
        response = auth_client.get("/profile")
        assert response.status_code == 200

    def test_authenticated_shows_seed_user_info(self, auth_client):
        response = auth_client.get("/profile")
        html = response.get_data(as_text=True)
        assert "Demo User" in html
        assert "demo@spendly.com" in html

    def test_authenticated_shows_rs_symbol(self, auth_client):
        response = auth_client.get("/profile")
        html = response.get_data(as_text=True)
        assert "Rs" in html

    def test_authenticated_shows_transaction_count(self, auth_client):
        response = auth_client.get("/profile")
        html = response.get_data(as_text=True)
        assert "8" in html  # 8 seed transactions

    def test_authenticated_shows_top_category(self, auth_client):
        response = auth_client.get("/profile")
        html = response.get_data(as_text=True)
        assert "Bills" in html  # Top category by amount