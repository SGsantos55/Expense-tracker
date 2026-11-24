"""Pure query functions for profile & financial settings — no Flask imports."""
from database.db import get_db


# ------------------------------------------------------------------ #
# Categories                                                           #
# ------------------------------------------------------------------ #

def get_categories(user_id, type=None, include_archived=False):
    """Return a user's categories, optionally filtered by type/archived state."""
    conn = get_db()
    try:
        query = (
            "SELECT id, name, type, icon, color, is_archived "
            "FROM categories WHERE user_id = %s"
        )
        params = [user_id]
        if type:
            query += " AND type = %s"
            params.append(type)
        if not include_archived:
            query += " AND is_archived = 0"
        query += " ORDER BY name"

        rows = conn.execute(query, params).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "type": row["type"],
                "icon": row["icon"],
                "color": row["color"],
                "is_archived": bool(row["is_archived"]),
            }
            for row in rows
        ]
    finally:
        conn.close()


def create_category(user_id, name, category_type, icon=None, color=None):
    """Insert a new category for the user and return its id."""
    conn = get_db()
    try:
        row = conn.execute(
            "INSERT INTO categories (user_id, name, type, icon, color) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (user_id, name, category_type, icon, color)
        ).fetchone()
        conn.commit()
        return row["id"]
    finally:
        conn.close()


def update_category(category_id, user_id, name, icon=None, color=None):
    """Rename/re-icon/recolor a category owned by the user."""
    conn = get_db()
    try:
        cursor = conn.execute(
            "UPDATE categories SET name = %s, icon = %s, color = %s "
            "WHERE id = %s AND user_id = %s",
            (name, icon, color, category_id, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def set_category_archived(category_id, user_id, archived):
    """Archive or restore a category owned by the user."""
    conn = get_db()
    try:
        cursor = conn.execute(
            "UPDATE categories SET is_archived = %s WHERE id = %s AND user_id = %s",
            (1 if archived else 0, category_id, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_category(category_id, user_id):
    """Permanently delete a category if it has no expenses using it.

    Returns "deleted", "in_use", or "not_found".
    """
    conn = get_db()
    try:
        category = conn.execute(
            "SELECT id, name FROM categories WHERE id = %s AND user_id = %s",
            (category_id, user_id)
        ).fetchone()
        if not category:
            return "not_found"

        in_use = conn.execute(
            "SELECT 1 FROM expenses WHERE user_id = %s AND category = %s LIMIT 1",
            (user_id, category["name"])
        ).fetchone()
        if in_use:
            return "in_use"

        conn.execute(
            "DELETE FROM budgets WHERE category_id = %s AND user_id = %s",
            (category_id, user_id)
        )
        conn.execute(
            "DELETE FROM categories WHERE id = %s AND user_id = %s",
            (category_id, user_id)
        )
        conn.commit()
        return "deleted"
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Income                                                               #
# ------------------------------------------------------------------ #

def get_income_entries(user_id):
    """Return a user's income history, most recent effective month first."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, source, amount, effective_month, created_at "
            "FROM income_entries WHERE user_id = %s "
            "ORDER BY effective_month DESC, id DESC",
            (user_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def add_income_entry(user_id, source, amount, effective_month):
    """Insert a new income history entry and return its id."""
    conn = get_db()
    try:
        row = conn.execute(
            "INSERT INTO income_entries (user_id, source, amount, effective_month) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (user_id, source, amount, effective_month)
        ).fetchone()
        conn.commit()
        return row["id"]
    finally:
        conn.close()


def delete_income_entry(entry_id, user_id):
    """Delete an income entry owned by the user."""
    conn = get_db()
    try:
        cursor = conn.execute(
            "DELETE FROM income_entries WHERE id = %s AND user_id = %s",
            (entry_id, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Budgets                                                              #
# ------------------------------------------------------------------ #

def get_budgets(user_id):
    """Return every budget row (overall has category_id = None) for the user."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, category_id, monthly_limit FROM budgets WHERE user_id = %s",
            (user_id,)
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def set_overall_budget(user_id, monthly_limit):
    """Create or update the user's overall monthly budget."""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM budgets WHERE user_id = %s AND category_id IS NULL",
            (user_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE budgets SET monthly_limit = %s WHERE id = %s",
                (monthly_limit, existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO budgets (user_id, category_id, monthly_limit) "
                "VALUES (%s, NULL, %s)",
                (user_id, monthly_limit)
            )
        conn.commit()
    finally:
        conn.close()


def set_category_budget(user_id, category_id, monthly_limit):
    """Create or update a per-category monthly budget."""
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM budgets WHERE user_id = %s AND category_id = %s",
            (user_id, category_id)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE budgets SET monthly_limit = %s WHERE id = %s",
                (monthly_limit, existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO budgets (user_id, category_id, monthly_limit) "
                "VALUES (%s, %s, %s)",
                (user_id, category_id, monthly_limit)
            )
        conn.commit()
    finally:
        conn.close()


def get_budget_consumption(user_id, date_from, date_to):
    """Return overall and per-category expense totals for a date range.

    Shape: {"overall": float, "by_category": {category_name: float}}
    """
    conn = get_db()
    try:
        overall_row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses "
            "WHERE user_id = %s AND date BETWEEN %s AND %s",
            (user_id, date_from, date_to)
        ).fetchone()

        by_category_rows = conn.execute(
            "SELECT category, SUM(amount) AS total FROM expenses "
            "WHERE user_id = %s AND date BETWEEN %s AND %s GROUP BY category",
            (user_id, date_from, date_to)
        ).fetchall()

        return {
            "overall": overall_row["total"] or 0.0,
            "by_category": {row["category"]: row["total"] for row in by_category_rows},
        }
    finally:
        conn.close()


# ------------------------------------------------------------------ #
# Preferences                                                          #
# ------------------------------------------------------------------ #

def get_user_preferences(user_id):
    """Return a user's display/financial preferences as a dict."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT preferred_currency, financial_month_start_day, date_format, "
            "number_format, default_export_format FROM users WHERE id = %s",
            (user_id,)
        ).fetchone()
        return dict(row) if row else {}
    finally:
        conn.close()


def update_user_preferences(user_id, preferred_currency, financial_month_start_day,
                             date_format, number_format, default_export_format):
    """Persist a user's display/financial preferences."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET preferred_currency = %s, financial_month_start_day = %s, "
            "date_format = %s, number_format = %s, default_export_format = %s "
            "WHERE id = %s",
            (preferred_currency, financial_month_start_day, date_format,
             number_format, default_export_format, user_id)
        )
        conn.commit()
    finally:
        conn.close()
