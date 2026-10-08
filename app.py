from flask import Flask, render_template, request, redirect, flash, url_for, session, g, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date as date_obj, timedelta
from database.db import get_db, init_db, seed_db
from database.queries import get_user_by_id, get_summary_stats, get_recent_transactions, get_category_breakdown, insert_expense, get_expense_by_id, update_expense, delete_expense as db_delete_expense

VALID_CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]

app = Flask(__name__)
app.secret_key = "spendly-dev-secret-key-change-in-production"

with app.app_context():
    init_db()
    seed_db()



# ------------------------------------------------------------------ #
# Session management                                                   #
# ------------------------------------------------------------------ #

@app.before_request
def load_user():
    g.user_id = session.get("user_id")


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def validate_expense_form(form):
    """Validate expense form data. Returns a list of error strings."""
    errors = []
    amount_str = form.get("amount", "").strip()
    category = form.get("category", "").strip()
    date_str = form.get("date", "").strip()

    if not amount_str:
        errors.append("Amount is required")
    else:
        try:
            amount = float(amount_str)
            if amount <= 0:
                errors.append("Amount must be greater than zero")
        except ValueError:
            errors.append("Amount must be a valid number")

    if not category:
        errors.append("Category is required")
    elif category not in VALID_CATEGORIES:
        errors.append("Please select a valid category")

    if not date_str:
        errors.append("Date is required")
    else:
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            errors.append("Date must be in YYYY-MM-DD format")

    return errors


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/<path:filename>")
def public_assets(filename):
    allowed = {
        "favicon-96x96.png",
        "favicon.svg",
        "favicon.ico",
        "apple-touch-icon.png",
        "site.webmanifest",
        "web-app-manifest-192x192.png",
        "web-app-manifest-512x512.png",
    }
    if filename not in allowed:
        return "", 404
    return send_from_directory("public", filename)


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


@app.route("/expenses/add", methods=["GET", "POST"])
def add_expense():
    if not g.user_id:
        return redirect(url_for("login"))

    if request.method == "POST":
        amount_str = request.form.get("amount", "").strip()
        category = request.form.get("category", "").strip()
        date_str = request.form.get("date", "").strip()
        description_raw = request.form.get("description", "").strip()
        description = None if not description_raw else description_raw

        errors = validate_expense_form(request.form)

        if errors:
            return render_template(
                "expenses/add_expense.html",
                errors=errors,
                amount=amount_str,
                category=category,
                date=date_str,
                description=description_raw
            )

        try:
            insert_expense(
                user_id=g.user_id,
                amount=float(amount_str),
                category=category,
                date=date_str,
                description=description
            )
            flash("Expense added successfully!")
            return redirect(url_for("profile"))
        except Exception as e:
            app.logger.error(f"Failed to insert expense: {e}")
            flash("An error occurred while saving your expense. Please try again.")
            return render_template(
                "expenses/add_expense.html",
                errors=["An error occurred while saving your expense. Please try again."],
                amount=amount_str,
                category=category,
                date=date_str,
                description=description_raw
            )

    today = date_obj.today().strftime("%Y-%m-%d")
    return render_template("expenses/add_expense.html", date=today)


@app.route("/expenses/<int:id>/edit", methods=["GET", "POST"])
def edit_expense(id):
    if not g.user_id:
        return redirect(url_for("login"))

    if request.method == "GET":
        expense = get_expense_by_id(id, g.user_id)
        if expense is None:
            # Not found or not owned by user
            return "", 404

        return render_template(
            "expenses/edit_expense.html",
            expense=expense,
            categories=VALID_CATEGORIES
        )

    # POST request
    expense = get_expense_by_id(id, g.user_id)
    if expense is None:
        # Not found or not owned by user
        return "", 404

    # Validate form data using the same validation as add_expense
    errors = validate_expense_form(request.form)

    if errors:
        # Re-render form with errors and submitted values
        return render_template(
            "expenses/edit_expense.html",
            errors=errors,
            amount=request.form.get("amount", "").strip(),
            category=request.form.get("category", "").strip(),
            date=request.form.get("date", "").strip(),
            description=request.form.get("description", "").strip(),
            expense={"id": id}  # Pass minimal expense obj for form action URL
        )

    # Update the expense
    amount_str = request.form.get("amount", "").strip()
    category = request.form.get("category", "").strip()
    date_str = request.form.get("date", "").strip()
    description_raw = request.form.get("description", "").strip()
    description = None if not description_raw else description_raw

    success = update_expense(
        expense_id=id,
        user_id=g.user_id,
        amount=float(amount_str),
        category=category,
        date=date_str,
        description=description
    )

    if success:
        flash("Expense updated successfully!")
        return redirect(url_for("profile"))
    else:
        # This shouldn't happen if we got the expense earlier, but handle gracefully
        flash("An error occurred while updating your expense. Please try again.")
        return render_template(
            "expenses/edit_expense.html",
            errors=["An error occurred while updating your expense. Please try again."],
            amount=amount_str,
            category=category,
            date=date_str,
            description=description_raw,
            expense={"id": id}
        )


@app.route("/expenses/<int:id>/delete", methods=["POST"])
def delete_expense(id):
    if not g.user_id:
        return redirect(url_for("login"))

    expense = get_expense_by_id(id, g.user_id)
    if expense is None:
        return "", 404

    if db_delete_expense(id, g.user_id):
        flash("Expense deleted successfully!")
    else:
        flash("An error occurred while deleting the expense.")

    return redirect(url_for("profile"))



if __name__ == "__main__":
    with app.app_context():
        init_db()
        seed_db()
    app.run(debug=True, port=5001)
