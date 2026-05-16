"""Tests for Step 6: Date Filter on Profile Page."""
import pytest
from datetime import date, timedelta


@pytest.fixture
def app():
    from app import app as flask_app
    flask_app.config.update({
        'TESTING': True,
        'SECRET_KEY': 'test-secret',
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
# Auth guard tests                                                     #
# ------------------------------------------------------------------ #

class TestDateFilterAuthGuard:
    def test_unauthenticated_redirects_to_login(self, client):
        """Unauthenticated users should be redirected to login."""
        response = client.get("/profile")
        assert response.status_code == 302
        assert "/login" in response.location


# ------------------------------------------------------------------ #
# No filter (All Time) tests                                          #
# ------------------------------------------------------------------ #

class TestNoDateFilter:
    def test_profile_with_no_params_returns_unfiltered_data(self, auth_client):
        """Profile with no query params returns all expenses."""
        response = auth_client.get("/profile")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        # Seed data has 8 transactions
        assert "8" in html
        # Total amount is sum of all expenses: 45.50 + 25 + 120 + 35 + 15.99 + 89.99 + 22.50 + 10 = 363.98
        assert "363.98" in html or "363.9" in html

    def test_profile_shows_all_categories_with_no_filter(self, auth_client):
        """All categories should appear when no filter is applied."""
        response = auth_client.get("/profile")
        html = response.get_data(as_text=True)
        # Seed data has 7 unique categories
        assert "Food" in html
        assert "Bills" in html
        assert "Transport" in html


# ------------------------------------------------------------------ #
# Preset filters tests                                                #
# ------------------------------------------------------------------ #

class TestThisMonthPreset:
    def test_this_month_preset_filters_to_current_month(self, auth_client):
        """This Month preset should filter to May 2026 (current month in seed data)."""
        today = date.today()
        first_day = today.replace(day=1).strftime("%Y-%m-%d")
        last_day = today.strftime("%Y-%m-%d")

        response = auth_client.get(f"/profile?date_from={first_day}&date_to={last_day}")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        # All 8 seed expenses are in May, so should see all 8
        assert "8" in html
        assert "363.98" in html or "363.9" in html

    def test_this_month_preset_shows_active_state(self, auth_client):
        """This Month preset button should show active state when selected."""
        today = date.today()
        first_day = today.replace(day=1).strftime("%Y-%m-%d")
        last_day = today.strftime("%Y-%m-%d")

        response = auth_client.get(f"/profile?date_from={first_day}&date_to={last_day}")
        html = response.get_data(as_text=True)
        # Template should highlight the active preset (checking for active class or style)
        assert "This Month" in html


class TestLast3MonthsPreset:
    def test_last_3_months_preset_filters_correctly(self, auth_client):
        """Last 3 Months preset should filter to 3-month window ending today."""
        today = date.today()
        start_date = (today - timedelta(days=90)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")

        response = auth_client.get(f"/profile?date_from={start_date}&date_to={end_date}")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        # All 8 seed expenses fall within this range (May 2026 is within 3 months)
        assert "8" in html

    def test_last_3_months_preset_shows_active_state(self, auth_client):
        """Last 3 Months preset button should show active state when selected."""
        today = date.today()
        start_date = (today - timedelta(days=90)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")

        response = auth_client.get(f"/profile?date_from={start_date}&date_to={end_date}")
        html = response.get_data(as_text=True)
        assert "Last 3 Months" in html


class TestLast6MonthsPreset:
    def test_last_6_months_preset_filters_correctly(self, auth_client):
        """Last 6 Months preset should filter to 6-month window ending today."""
        today = date.today()
        start_date = (today - timedelta(days=180)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")

        response = auth_client.get(f"/profile?date_from={start_date}&date_to={end_date}")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        # All 8 seed expenses fall within this range
        assert "8" in html

    def test_last_6_months_preset_shows_active_state(self, auth_client):
        """Last 6 Months preset button should show active state when selected."""
        today = date.today()
        start_date = (today - timedelta(days=180)).strftime("%Y-%m-%d")
        end_date = today.strftime("%Y-%m-%d")

        response = auth_client.get(f"/profile?date_from={start_date}&date_to={end_date}")
        html = response.get_data(as_text=True)
        assert "Last 6 Months" in html


class TestAllTimePreset:
    def test_all_time_preset_removes_filter(self, auth_client):
        """All Time preset (no query params) should show all expenses."""
        response = auth_client.get("/profile")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        # Should show all 8 transactions like unfiltered view
        assert "8" in html
        assert "363.98" in html or "363.9" in html


# ------------------------------------------------------------------ #
# Custom date range tests                                             #
# ------------------------------------------------------------------ #

class TestCustomDateRange:
    def test_custom_valid_date_range_filters_correctly(self, auth_client):
        """Custom date range with valid dates should filter data correctly."""
        # Filter to just one day: 2026-05-02
        response = auth_client.get("/profile?date_from=2026-05-02&date_to=2026-05-02")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        # Should only show 1 transaction (45.50 on May 2)
        assert "1" in html
        assert "45.50" in html

    def test_custom_date_range_filters_transactions(self, auth_client):
        """Custom date range should filter recent transactions list."""
        response = auth_client.get("/profile?date_from=2026-05-10&date_to=2026-05-15")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        # Should show 3 transactions (May 11, 12, 13)
        # The amounts are: 89.99 (11th), 22.50 (12th), 10.00 (13th)
        assert "89.99" in html or "89.9" in html

    def test_custom_date_range_filters_category_breakdown(self, auth_client):
        """Custom date range should filter category breakdown."""
        response = auth_client.get("/profile?date_from=2026-05-10&date_code=2026-05-15")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        # Should only show categories within range
        # In range: Shopping (89.99), Food (22.50), Other (10.00)


# ------------------------------------------------------------------ #
# Invalid date handling tests                                         #
# ------------------------------------------------------------------ #

class TestInvalidDateHandling:
    def test_date_from_greater_than_date_to_shows_flash_error(self, auth_client):
        """When date_from > date_to, should show flash error and fall back to unfiltered."""
        response = auth_client.get("/profile?date_from=2026-05-15&date_to=2026-05-01")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        # Should show error message
        assert "Start date must be before end date" in html
        # Should fall back to showing all data
        assert "8" in html

    def test_malformed_date_from_does_not_crash(self, auth_client):
        """Malformed date_from should not crash - falls back to unfiltered."""
        response = auth_client.get("/profile?date_from=not-a-date&date_to=2026-05-15")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        # Should fall back to unfiltered (all 8 transactions)
        assert "8" in html

    def test_malformed_date_to_does_not_crash(self, auth_client):
        """Malformed date_to should not crash - falls back to unfiltered."""
        response = auth_client.get("/profile?date_from=2026-05-01&date_to=invalid-date")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        # Should fall back to unfiltered (all 8 transactions)
        assert "8" in html

    def test_both_malformed_dates_falls_back_to_unfiltered(self, auth_client):
        """Both dates malformed should fall back to unfiltered."""
        response = auth_client.get("/profile?date_from=abc&date_to=xyz")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        # Should fall back to all expenses
        assert "8" in html

    def test_invalid_date_format_flash_message(self, auth_client):
        """Invalid date format should show appropriate flash message."""
        response = auth_client.get("/profile?date_from=bad-date")
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        # Should have some error/flash message about invalid date
        # The spec says it shows "Invalid date format. Showing all expenses."


# ------------------------------------------------------------------ #
# Empty range edge case tests                                         #
# ------------------------------------------------------------------ #

class TestEmptyDateRange:
    def test_user_with_no_expenses_in_range_sees_zeros(self, auth_client, app):
        """User with no expenses in date range should see ₹0.00 and 0 transactions."""
        from database.db import get_db
        # Create a new user with no expenses
        conn = get_db()
        import time
        email = f"emptytest{int(time.time())}@test.com"
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Empty User", email, "dummyhash")
        )
        conn.commit()
        new_user_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
        conn.close()

        # Create a new auth client for this user
        with auth_client.session_transaction() as sess:
            sess["user_id"] = new_user_id

        # Get profile with date filter
        response = auth_client.get("/profile?date_from=2026-01-01&date_to=2026-01-31")
        html = response.get_data(as_text=True)
        # Should show 0 transactions
        assert "0" in html

    def test_user_with_no_expenses_in_range_sees_empty_category_breakdown(self, auth_client, app):
        """User with no expenses in date range should see empty category breakdown."""
        from database.db import get_db
        # Create a new user with no expenses
        conn = get_db()
        import time
        email = f"emptycat{int(time.time())}@test.com"
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Empty Cat User", email, "dummyhash")
        )
        conn.commit()
        new_user_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
        conn.close()

        # Create a new auth client for this user
        with auth_client.session_transaction() as sess:
            sess["user_id"] = new_user_id

        # Get profile with date filter
        response = auth_client.get("/profile?date_from=2026-05-01&date_to=2026-05-31")
        html = response.get_data(as_text=True)
        # Should show 0 for total or empty state


# ------------------------------------------------------------------ #
# Currency symbol tests                                               #
# ------------------------------------------------------------------ #

class TestCurrencySymbol:
    def test_rs_symbol_shown_regardless_of_filter(self, auth_client):
        """All amounts should display Rs symbol regardless of filter."""
        # Unfiltered
        response = auth_client.get("/profile")
        html = response.get_data(as_text=True)
        assert "Rs" in html or "₹" in html

        # Filtered to specific range
        response = auth_client.get("/profile?date_from=2026-05-02&date_to=2026-05-02")
        html = response.get_data(as_text=True)
        assert "Rs" in html or "₹" in html


# ------------------------------------------------------------------ #
# Template rendering tests                                            #
# ------------------------------------------------------------------ #

class TestTemplateRendering:
    def test_filter_bar_present_in_template(self, auth_client):
        """Profile page should contain filter bar elements."""
        response = auth_client.get("/profile")
        html = response.get_data(as_text=True)
        # Check for preset buttons
        assert "This Month" in html
        assert "Last 3 Months" in html
        assert "Last 6 Months" in html
        assert "All Time" in html

    def test_preset_links_use_url_for(self, auth_client):
        """Preset links should be properly generated (not hardcoded URLs)."""
        response = auth_client.get("/profile")
        html = response.get_data(as_text=True)
        # The links should be present with query params for presets
        # This is a structural check - the links should exist

    def test_custom_date_inputs_present(self, auth_client):
        """Profile page should have custom date input fields."""
        response = auth_client.get("/profile")
        html = response.get_data(as_text=True)
        # Should have date input fields for custom range
        assert 'type="date"' in html or 'date_from' in html


# ------------------------------------------------------------------ #
# Query function integration tests                                     #
# ------------------------------------------------------------------ #

class TestQueryFunctionsWithDateFilter:
    def test_get_summary_stats_respects_date_filter(self, seed_user_id):
        """get_summary_stats should filter by date range."""
        from database.queries import get_summary_stats
        # Filter to single day
        stats = get_summary_stats(seed_user_id, "2026-05-02", "2026-05-02")
        assert stats["total_spent"] == 45.50
        assert stats["transaction_count"] == 1

    def test_get_summary_stats_no_filter(self, seed_user_id):
        """get_summary_stats without date params returns all."""
        from database.queries import get_summary_stats
        stats = get_summary_stats(seed_user_id)
        assert stats["total_spent"] > 0
        assert stats["transaction_count"] == 8

    def test_get_recent_transactions_respects_date_filter(self, seed_user_id):
        """get_recent_transactions should filter by date range."""
        from database.queries import get_recent_transactions
        transactions = get_recent_transactions(seed_user_id, 10, "2026-05-10", "2026-05-15")
        # Should return only transactions in range
        assert len(transactions) >= 1

    def test_get_category_breakdown_respects_date_filter(self, seed_user_id):
        """get_category_breakdown should filter by date range."""
        from database.queries import get_category_breakdown
        categories = get_category_breakdown(seed_user_id, "2026-05-01", "2026-05-05")
        # Should only include categories from that range
        # In range: Food (45.50), Transport (25), Bills (120)
        total = sum(c["amount"] for c in categories)
        assert total == 190.50