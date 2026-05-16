from flask import Flask, render_template, request, redirect, flash, url_for, session, g
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date as date_obj, timedelta
from database.db import get_db, init_db, seed_db
from database.queries import get_user_by_id, get_summary_stats, get_recent_transactions, get_category_breakdown

app = Flask(__name__)
app.secret_key = "spendly-dev-secret-key-change-in-production"


# ------------------------------------------------------------------ #
# Session management                                                   #
# ------------------------------------------------------------------ #

@app.before_request
def load_user():
    g.user_id = session.get("user_id")


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user_id:
        return redirect(url_for("profile"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        errors = []
        if not name:
            errors.append("Name is required")
        if not email or "@" not in email:
            errors.append("Valid email is required")
        if not password or len(password) < 6:
            errors.append("Password must be at least 6 characters")

        conn = get_db()
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            errors.append("Email already registered")

        if errors:
            conn.close()
            return render_template("register.html", errors=errors, name=name, email=email)

        password_hash = generate_password_hash(password)
        conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, password_hash)
        )
        conn.commit()
        conn.close()

        flash("Registration successful! Please log in.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.user_id:
        return redirect(url_for("profile"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        errors = []
        if not email or "@" not in email:
            errors.append("Valid email is required")
        if not password:
            errors.append("Password is required")

        if errors:
            return render_template("login.html", errors=errors, email=email)

        conn = get_db()
        user = conn.execute(
            "SELECT id, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            return redirect(url_for("profile"))

        return render_template("login.html", error="Invalid email or password", email=email)

    return render_template("login.html")


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/profile")
def profile():
    if not g.user_id:
        return redirect(url_for("login"))

    user = get_user_by_id(g.user_id)

    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    validated_from = None
    validated_to = None

    if date_from or date_to:
        try:
            if date_from:
                validated_from = datetime.strptime(date_from, "%Y-%m-%d").strftime("%Y-%m-%d")
            if date_to:
                validated_to = datetime.strptime(date_to, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            flash("Invalid date format. Showing all expenses.")
            validated_from = None
            validated_to = None

        if validated_from and validated_to:
            if validated_from > validated_to:
                flash("Start date must be before end date.")
                validated_from = None
                validated_to = None

    stats = get_summary_stats(g.user_id, validated_from, validated_to)
    recent = get_recent_transactions(g.user_id, 10, validated_from, validated_to)
    categories = get_category_breakdown(g.user_id, validated_from, validated_to)

    today = date_obj.today()
    first_day_of_month = today.replace(day=1)

    return render_template("profile.html",
        user=user,
        total=stats["total_spent"],
        this_month=0.0,
        last_month=0.0,
        transaction_count=stats["transaction_count"],
        top_category=stats["top_category"],
        categories=categories,
        recent=recent,
        date_from=validated_from,
        date_to=validated_to,
        preset_this_month_from=first_day_of_month.strftime("%Y-%m-%d"),
        preset_this_month_to=today.strftime("%Y-%m-%d"),
        preset_3months_from=(today - timedelta(days=90)).strftime("%Y-%m-%d"),
        preset_3months_to=today.strftime("%Y-%m-%d"),
        preset_6months_from=(today - timedelta(days=180)).strftime("%Y-%m-%d"),
        preset_6months_to=today.strftime("%Y-%m-%d")
    )


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    with app.app_context():
        init_db()
        seed_db()
    app.run(debug=True, port=5001)
