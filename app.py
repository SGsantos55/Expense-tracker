from flask import Flask, render_template, request, redirect, flash, url_for, session, g, send_from_directory, Response, abort
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date as date_obj, timedelta
import os
import re
import secrets
import hashlib
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth
from database.db import get_db, init_db, seed_db
from database.queries import get_user_by_id, get_summary_stats, get_recent_transactions, get_category_breakdown, insert_expense, get_expense_by_id, update_expense, delete_expense as db_delete_expense, insert_contact_message, get_all_contact_messages, get_expenses_for_export, get_user_by_google_id, get_user_by_email, link_google_id, create_oauth_user, get_user_by_email_for_auth, set_email_verified, update_password_hash, create_auth_token, get_valid_auth_token, mark_token_used, delete_user
from database.excel import build_expense_workbook
from database.mailer import send_verification_email, send_password_reset_email

load_dotenv()

VALID_CATEGORIES = ["Food", "Transport", "Bills", "Health", "Entertainment", "Shopping", "Other"]

CUSTOM_CATEGORY_SENTINEL = "__custom__"
CUSTOM_CATEGORY_MAX_LENGTH = 30
CUSTOM_CATEGORY_PATTERN = re.compile(r"^[A-Za-z0-9 ]+$")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")

app = Flask(__name__)
app.secret_key = "spendly-dev-secret-key-change-in-production"

# ------------------------------------------------------------------ #
# OAuth (Google) configuration                                        #
# ------------------------------------------------------------------ #

oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=os.environ.get("OAUTH_CLIENT_ID"),
    client_secret=os.environ.get("OAUTH_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

with app.app_context():
    init_db()
    seed_db()



# ------------------------------------------------------------------ #
# Session management                                                   #
# ------------------------------------------------------------------ #

@app.before_request
def load_user():
    g.user_id = session.get("user_id")


@app.context_processor
def inject_categories():
    """Make preset categories and the custom sentinel available to all templates."""
    return {
        "valid_categories": VALID_CATEGORIES,
        "custom_category_sentinel": CUSTOM_CATEGORY_SENTINEL,
        "custom_category_max_length": CUSTOM_CATEGORY_MAX_LENGTH,
    }


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def resolve_category(form):
    """Return the effective category, resolving the custom-category sentinel."""
    category = form.get("category", "").strip()
    if category == CUSTOM_CATEGORY_SENTINEL:
        return form.get("custom_category", "").strip()
    return category


def validate_expense_form(form):
    """Validate expense form data. Returns a list of error strings."""
    errors = []
    amount_str = form.get("amount", "").strip()
    category_choice = form.get("category", "").strip()
    custom_category = form.get("custom_category", "").strip()
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

    if not category_choice:
        errors.append("Category is required")
    elif category_choice == CUSTOM_CATEGORY_SENTINEL:
        if not custom_category:
            errors.append("Category is required")
        elif len(custom_category) > CUSTOM_CATEGORY_MAX_LENGTH:
            errors.append(
                f"Category must be {CUSTOM_CATEGORY_MAX_LENGTH} characters or fewer"
            )
        elif not CUSTOM_CATEGORY_PATTERN.match(custom_category):
            errors.append("Category can only contain letters, numbers and spaces")
    elif category_choice not in VALID_CATEGORIES:
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
# Email-token helpers (verification & password reset)                 #
# ------------------------------------------------------------------ #

VERIFY_TOKEN_TTL = timedelta(hours=24)
RESET_TOKEN_TTL = timedelta(hours=1)


def _hash_token(raw_token):
    """Return the sha256 hex digest stored in the database for a raw token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _issue_token(user_id, purpose, ttl):
    """Create a single-use token row and return the raw (un-hashed) token."""
    raw_token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + ttl).strftime("%Y-%m-%d %H:%M:%S")
    create_auth_token(user_id, _hash_token(raw_token), purpose, expires_at)
    return raw_token


def _send_verification(user_id, email):
    """Issue a verification token and email the link. Returns True on success."""
    raw_token = _issue_token(user_id, "verify_email", VERIFY_TOKEN_TTL)
    link = url_for("verify_email", token=raw_token, _external=True)
    try:
        send_verification_email(email, link)
        return True
    except Exception as e:
        app.logger.error(f"Failed to send verification email: {e}")
        return False


def _send_password_reset(user_id, email):
    """Issue a reset token and email the link. Returns True on success."""
    raw_token = _issue_token(user_id, "password_reset", RESET_TOKEN_TTL)
    link = url_for("reset_password", token=raw_token, _external=True)
    try:
        send_password_reset_email(email, link)
        return True
    except Exception as e:
        app.logger.error(f"Failed to send password reset email: {e}")
        return False


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
        abort(404)
    return send_from_directory("public", filename)


@app.route("/robots.txt")
def robots_txt():
    lines = [
        "User-agent: *",
        "Allow: /",
        "Disallow: /profile",
        "Disallow: /expenses/",
        "Disallow: /logout",
        f"Sitemap: {request.url_root}sitemap.xml",
    ]
    return Response("\n".join(lines) + "\n", mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    root = request.url_root
    public_pages = ["", "login", "register", "terms", "privacy", "about", "contact"]
    urls = "".join(
        f"<url><loc>{root}{path}</loc><changefreq>weekly</changefreq></url>"
        for path in public_pages
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>"
    )
    return Response(xml, mimetype="application/xml")


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
        existing = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()
        if existing:
            errors.append("Email already registered")

        if errors:
            conn.close()
            return render_template("register.html", errors=errors, name=name, email=email)

        password_hash = generate_password_hash(password)
        new_user = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s) RETURNING id",
            (name, email, password_hash)
        ).fetchone()
        conn.commit()
        conn.close()

        sent = _send_verification(new_user["id"], email)
        if sent:
            flash("Registration successful! Check your email to verify your account before signing in.")
        else:
            flash("Registration successful, but we couldn't send your verification email. You can request a new one from the sign-in page.")
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
            "SELECT id, password_hash, email_verified FROM users WHERE email = %s", (email,)
        ).fetchone()
        conn.close()

        if user and user["password_hash"] and check_password_hash(user["password_hash"], password):
            if not user["email_verified"]:
                return render_template(
                    "login.html",
                    error="Please verify your email before signing in.",
                    unverified_email=email,
                    email=email,
                )
            session["user_id"] = user["id"]
            return redirect(url_for("profile"))

        return render_template("login.html", error="Invalid email or password", email=email)

    return render_template("login.html")


# ------------------------------------------------------------------ #
# Google OAuth login                                                   #
# ------------------------------------------------------------------ #

@app.route("/login/google")
def login_google():
    redirect_uri = url_for("login_google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@app.route("/login/google/callback")
def login_google_callback():
    try:
        token = oauth.google.authorize_access_token()
    except Exception as e:
        app.logger.error(f"Google OAuth failed: {e}")
        flash("Google sign-in failed. Please try again.")
        return redirect(url_for("login"))

    userinfo = token.get("userinfo")
    if not userinfo:
        userinfo = oauth.google.userinfo(token=token)

    google_id = userinfo.get("sub")
    email = (userinfo.get("email") or "").strip().lower()
    name = userinfo.get("name") or (email.split("@")[0] if email else "User")

    if not google_id or not email:
        flash("Google sign-in did not return the required account details.")
        return redirect(url_for("login"))

    # Match by google_id first, then link an existing email account, else create.
    user = get_user_by_google_id(google_id)
    if user:
        user_id = user["id"]
    else:
        existing = get_user_by_email(email)
        if existing:
            user_id = existing["id"]
            if not existing["google_id"]:
                link_google_id(user_id, google_id)
        else:
            user_id = create_oauth_user(name, email, google_id)

    session["user_id"] = user_id
    return redirect(url_for("profile"))


# ------------------------------------------------------------------ #
# Email verification                                                   #
# ------------------------------------------------------------------ #

@app.route("/verify/<token>")
def verify_email(token):
    record = get_valid_auth_token(_hash_token(token), "verify_email")
    if not record:
        flash("This verification link is invalid or has expired.")
        return redirect(url_for("login"))

    set_email_verified(record["user_id"])
    mark_token_used(record["id"])
    flash("Your email has been verified. You can now sign in.")
    return redirect(url_for("login"))


@app.route("/verify/resend", methods=["POST"])
def verify_resend():
    email = request.form.get("email", "").strip().lower()
    user = get_user_by_email_for_auth(email) if email else None
    # Only (re)send to real, password-based, still-unverified accounts.
    if user and user["password_hash"] and not user["email_verified"]:
        _send_verification(user["id"], user["email"])
    flash("If that account exists and needs verifying, we've sent a new verification email.")
    return redirect(url_for("login"))


# ------------------------------------------------------------------ #
# Password reset                                                       #
# ------------------------------------------------------------------ #

@app.route("/password/forgot", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = get_user_by_email_for_auth(email) if email else None
        # Never reset OAuth-only accounts (no password); stay enumeration-safe.
        if user and user["password_hash"]:
            _send_password_reset(user["id"], user["email"])
        flash("If an account with that email exists, we've sent a password reset link.")
        return redirect(url_for("login"))

    return render_template("auth/forgot_password.html")


@app.route("/password/reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    record = get_valid_auth_token(_hash_token(token), "password_reset")
    if not record:
        flash("This password reset link is invalid or has expired.")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        errors = []
        if not password or len(password) < 6:
            errors.append("Password must be at least 6 characters")
        if password != confirm:
            errors.append("Passwords do not match")

        if errors:
            return render_template("auth/reset_password.html", errors=errors, token=token)

        update_password_hash(record["user_id"], generate_password_hash(password))
        mark_token_used(record["id"])
        flash("Your password has been reset. Please sign in with your new password.")
        return redirect(url_for("login"))

    return render_template("auth/reset_password.html", token=token)


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()

        errors = []
        if not name:
            errors.append("Name is required")
        if not email or "@" not in email:
            errors.append("Valid email is required")
        if not subject:
            errors.append("Subject is required")
        if not message:
            errors.append("Message is required")

        if errors:
            return render_template(
                "contact.html",
                errors=errors,
                name=name,
                email=email,
                subject=subject,
                message=message
            )

        insert_contact_message(name, email, subject, message)
        flash("Thanks for reaching out! We'll get back to you soon.")
        return redirect(url_for("contact"))

    return render_template("contact.html")


@app.route("/admin/messages")
def admin_messages():
    if not g.user_id:
        abort(404)

    user = get_user_by_id(g.user_id)
    if not ADMIN_EMAIL or not user or user["email"] != ADMIN_EMAIL:
        abort(404)

    messages = get_all_contact_messages()
    return render_template("admin/messages.html", messages=messages)


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
    if user is None:
        session.clear()
        return redirect(url_for("login"))

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
        category_choice = request.form.get("category", "").strip()
        custom_category = request.form.get("custom_category", "").strip()
        category = resolve_category(request.form)
        date_str = request.form.get("date", "").strip()
        description_raw = request.form.get("description", "").strip()
        description = None if not description_raw else description_raw

        errors = validate_expense_form(request.form)

        if errors:
            return render_template(
                "expenses/add_expense.html",
                errors=errors,
                amount=amount_str,
                category=category_choice,
                custom_category=custom_category,
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
                category=category_choice,
                custom_category=custom_category,
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
            custom_category=request.form.get("custom_category", "").strip(),
            date=request.form.get("date", "").strip(),
            description=request.form.get("description", "").strip(),
            expense={"id": id}  # Pass minimal expense obj for form action URL
        )

    # Update the expense
    amount_str = request.form.get("amount", "").strip()
    category = resolve_category(request.form)
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
            category=request.form.get("category", "").strip(),
            custom_category=request.form.get("custom_category", "").strip(),
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


@app.route("/profile/delete", methods=["POST"])
def delete_account():
    if not g.user_id:
        return redirect(url_for("login"))

    if delete_user(g.user_id):
        session.clear()
        flash("Your account has been permanently deleted.")
    else:
        flash("An error occurred while trying to delete your account.")

    return redirect(url_for("landing"))


@app.route("/expenses/export")
def export_expenses():
    if not g.user_id:
        return redirect(url_for("login"))

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
            validated_from = None
            validated_to = None

        if validated_from and validated_to and validated_from > validated_to:
            validated_from = None
            validated_to = None

    rows = get_expenses_for_export(g.user_id, validated_from, validated_to)
    workbook_bytes = build_expense_workbook(rows)

    filename = f"expenses_{date_obj.today().strftime('%Y-%m-%d')}.xlsx"
    return Response(
        workbook_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ------------------------------------------------------------------ #
# Error handlers                                                      #
# ------------------------------------------------------------------ #

@app.errorhandler(404)
def not_found(error):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(error):
    return render_template("500.html"), 500


if __name__ == "__main__":
    with app.app_context():
        init_db()
        seed_db()
    app.run(debug=True, port=5001)
