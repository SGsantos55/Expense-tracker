"""Pure query functions for profile page data — no Flask imports."""
from datetime import datetime
from database.db import get_db


def get_user_by_id(user_id):
    """Return user info dict or None if not found."""
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT name, email, created_at FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        if not user:
            return None
        created = user["created_at"]
        if created:
            dt = datetime.strptime(created[:10], "%Y-%m-%d")
            member_since = dt.strftime("%B %Y")
        else:
            member_since = "Unknown"
        return {
            "name": user["name"],
            "email": user["email"],
            "member_since": member_since
        }
    finally:
        conn.close()


def get_summary_stats(user_id, date_from=None, date_to=None):
    """Return dict with total_spent, transaction_count, top_category."""
    conn = get_db()
    try:
        params = [user_id]
        date_filter = ""
        if date_from and date_to:
            date_filter = " AND date BETWEEN ? AND ?"
            params.extend([date_from, date_to])

        total_row = conn.execute(
            f"SELECT SUM(amount) as total, COUNT(*) as count FROM expenses WHERE user_id = ?{date_filter}",
            params
        ).fetchone()

        total_spent = total_row["total"] or 0.0
        transaction_count = total_row["count"] or 0

        top_cat_row = conn.execute(
            f"""SELECT category, SUM(amount) as total
               FROM expenses WHERE user_id = ?{date_filter}
               GROUP BY category ORDER BY total DESC LIMIT 1""",
            params
        ).fetchone()

        top_category = top_cat_row["category"] if top_cat_row else "—"

        return {
            "total_spent": total_spent,
            "transaction_count": transaction_count,
            "top_category": top_category
        }
    finally:
        conn.close()


def get_recent_transactions(user_id, limit=10, date_from=None, date_to=None):
    """Return list of recent expenses, newest first."""
    conn = get_db()
    try:
        params = [user_id, limit]
        date_filter = ""
        if date_from and date_to:
            date_filter = " AND date BETWEEN ? AND ?"
            params = [user_id] + [date_from, date_to] + [limit]

        rows = conn.execute(
            f"""SELECT id, date, description, category, amount
               FROM expenses WHERE user_id = ?{date_filter}
               ORDER BY date DESC, id DESC LIMIT ?""",
            params
        ).fetchall()
        return [
            {
                "id": row["id"],
                "date": row["date"],
                "description": row["description"] or "",
                "category": row["category"],
                "amount": row["amount"]
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_expense_by_id(expense_id, user_id):
    """Return a single expense dict if it belongs to the user, None otherwise."""
    conn = get_db()
    try:
        expense = conn.execute(
            """SELECT id, amount, category, date, description
               FROM expenses WHERE id = ? AND user_id = ?""",
            (expense_id, user_id)
        ).fetchone()

        if not expense:
            return None

        return {
            "id": expense["id"],
            "amount": expense["amount"],
            "category": expense["category"],
            "date": expense["date"],
            "description": expense["description"]
        }
    finally:
        conn.close()


def update_expense(expense_id, user_id, amount, category, date, description=None):
    """Update an existing expense if it belongs to the user.

    Args:
        expense_id (int): The ID of the expense to update
        user_id (int): The ID of the user (for ownership verification)
        amount (float): The expense amount
        category (str): The expense category
        date (str): The expense date in YYYY-MM-DD format
        description (str, optional): The expense description

    Returns:
        bool: True if update succeeded, False otherwise
    """
    conn = get_db()
    try:
        cursor = conn.execute(
            """UPDATE expenses
               SET amount = ?, category = ?, date = ?, description = ?
               WHERE id = ? AND user_id = ?""",
            (amount, category, date, description, expense_id, user_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_category_breakdown(user_id, date_from=None, date_to=None):
    """Return list of categories with amounts and percentages summing to 100."""
    conn = get_db()
    try:
        params = [user_id]
        date_filter = ""
        if date_from and date_to:
            date_filter = " AND date BETWEEN ? AND ?"
            params.extend([date_from, date_to])

        rows = conn.execute(
            f"""SELECT category, SUM(amount) as total
               FROM expenses WHERE user_id = ?{date_filter}
               GROUP BY category ORDER BY total DESC""",
            params
        ).fetchall()

        if not rows:
            return []

        total_amount = sum(row["total"] for row in rows)
        if total_amount == 0:
            return []

        categories = []
        raw_pcts = []
        for row in rows:
            pct = round((row["total"] / total_amount) * 100)
            raw_pcts.append(pct)
            categories.append({
                "name": row["category"],
                "amount": row["total"],
                "pct": pct
            })

        # Adjust largest to absorb rounding remainder
        remainder = 100 - sum(raw_pcts)
        if remainder != 0 and categories:
            largest_idx = max(range(len(categories)), key=lambda i: raw_pcts[i])
            categories[largest_idx]["pct"] += remainder

        return categories
    finally:
        conn.close()


def insert_expense(user_id, amount, category, date, description=None):
    """Insert a new expense for the given user.

    Args:
        user_id (int): The ID of the user
        amount (float): The expense amount
        category (str): The expense category
        date (str): The expense date in YYYY-MM-DD format
        description (str, optional): The expense description

    Returns:
        int: The ID of the newly inserted expense
    """
    conn = get_db()
    try:
        cursor = conn.execute(
            """INSERT INTO expenses (user_id, amount, category, date, description)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, amount, category, date, description)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()