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


def get_summary_stats(user_id):
    """Return dict with total_spent, transaction_count, top_category."""
    conn = get_db()
    try:
        total_row = conn.execute(
            "SELECT SUM(amount) as total, COUNT(*) as count FROM expenses WHERE user_id = ?",
            (user_id,)
        ).fetchone()

        total_spent = total_row["total"] or 0.0
        transaction_count = total_row["count"] or 0

        top_cat_row = conn.execute(
            """SELECT category, SUM(amount) as total
               FROM expenses WHERE user_id = ?
               GROUP BY category ORDER BY total DESC LIMIT 1""",
            (user_id,)
        ).fetchone()

        top_category = top_cat_row["category"] if top_cat_row else "—"

        return {
            "total_spent": total_spent,
            "transaction_count": transaction_count,
            "top_category": top_category
        }
    finally:
        conn.close()


def get_recent_transactions(user_id, limit=10):
    """Return list of recent expenses, newest first."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT date, description, category, amount
               FROM expenses WHERE user_id = ?
               ORDER BY date DESC, id DESC LIMIT ?""",
            (user_id, limit)
        ).fetchall()
        return [
            {
                "date": row["date"],
                "description": row["description"] or "",
                "category": row["category"],
                "amount": row["amount"]
            }
            for row in rows
        ]
    finally:
        conn.close()


def get_category_breakdown(user_id):
    """Return list of categories with amounts and percentages summing to 100."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT category, SUM(amount) as total
               FROM expenses WHERE user_id = ?
               GROUP BY category ORDER BY total DESC""",
            (user_id,)
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