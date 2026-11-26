from flask import Flask, render_template, request, redirect, flash, url_for, session, g, send_from_directory, Response, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime, date as date_obj, timedelta
import os
import re
import secrets
import hashlib
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth
from database.db import get_db, init_db, seed_db
from database.queries import get_user_by_id, get_summary_stats, get_recent_transactions, get_category_breakdown, insert_expense, get_expense_by_id, update_expense, delete_expense as db_delete_expense, insert_contact_message, get_all_contact_messages, get_expenses_for_export, get_user_by_google_id, get_user_by_email, link_google_id, create_oauth_user, get_user_by_email_for_auth, set_email_verified, update_password_hash, create_auth_token, get_valid_auth_token, mark_token_used, delete_user
from database.settings_queries import get_categories, create_category, update_category, set_category_archived, delete_category, get_income_entries, add_income_entry, delete_income_entry, get_budgets, set_overall_budget, set_category_budget, get_budget_consumption, get_user_preferences, update_user_preferences, seed_default_categories
from database.defaults import DEFAULT_EXPENSE_CATEGORIES
from database.excel import build_expense_workbook, TEMPLATES as EXPORT_TEMPLATES, DEFAULT_TEMPLATE
from database.pdf import build_expense_pdf
from database.mailer import send_verification_email, send_password_reset_email

load_dotenv()

VALID_CATEGORIES = [name for name, _color in DEFAULT_EXPENSE_CATEGORIES]
DEFAULT_CATEGORY_COLOR = DEFAULT_EXPENSE_CATEGORIES[0][1]

CUSTOM_CATEGORY_SENTINEL = "__custom__"
CUSTOM_CATEGORY_MAX_LENGTH = 30
CUSTOM_CATEGORY_PATTERN = re.compile(r"^[A-Za-z0-9 ]+$")

CURRENCY_CHOICES = ["USD", "EUR", "GBP", "INR", "NPR", "AUD", "CAD"]
CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "INR": "₹",
    "NPR": "Rs",
    "AUD": "A$",
    "CAD": "C$",
}
DATE_FORMAT_CHOICES = ["YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY"]
NUMBER_FORMAT_CHOICES = ["1,234.56", "1.234,56", "1 234.56"]
EXPORT_FORMAT_CHOICES = ["xlsx", "pdf"]
BUDGET_WARNING_THRESHOLD = 90

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "expense-tracker-dev-secret-key-change-in-production")

# Trust Render's (or any) reverse proxy so request.scheme reflects the original
# HTTPS request. Without this, url_for(_external=True) builds http:// URLs behind
# the proxy, which breaks the OAuth redirect_uri match.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

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
    """Make preset + user-defined categories and the custom sentinel available to all templates."""
    return {
        "valid_categories": _user_expense_categories(),
        "custom_category_sentinel": CUSTOM_CATEGORY_SENTINEL,
        "custom_category_max_length": CUSTOM_CATEGORY_MAX_LENGTH,
        "default_category_color": DEFAULT_CATEGORY_COLOR,
    }


@app.context_processor
def inject_currency():
    """Make the user's preferred currency symbol available to all templates."""
    currency_code = _user_preferences().get("preferred_currency", "NPR")
    return {
        "currency_code": currency_code,
        "currency_symbol": CURRENCY_SYMBOLS.get(currency_code, currency_code),
        "currency_symbols": CURRENCY_SYMBOLS,
    }


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _user_expense_categories():
    """Return the user's active expense category names.

    Preset categories live in the database (seeded per user) so they can be
    renamed, archived or budgeted. Fall back to the defaults only for users
    who have no categories recorded yet, or for anonymous visitors.
    """
    if not g.get("user_id"):
        return list(VALID_CATEGORIES)
    active = get_categories(g.user_id, type="expense", include_archived=False)
    if active:
        return [category["name"] for category in active]
    ever_created = get_categories(g.user_id, type="expense", include_archived=True)
    if not ever_created:
        return list(VALID_CATEGORIES)
    return []


# ------------------------------------------------------------------ #
# Preference-aware formatting                                          #
# ------------------------------------------------------------------ #

NUMBER_FORMATS = {
    "1,234.56": (",", "."),
    "1.234,56": (".", ","),
    "1 234.56": (" ", "."),
}

DATE_FORMATS = {
    "YYYY-MM-DD": "%Y-%m-%d",
    "DD/MM/YYYY": "%d/%m/%Y",
    "MM/DD/YYYY": "%m/%d/%Y",
}


def _user_preferences():
    """Return the signed-in user's preferences, cached for the request."""
    if not g.get("user_id"):
        return {}
    prefs = g.get("_user_prefs")
    if prefs is None:
        prefs = get_user_preferences(g.user_id) or {}
        g._user_prefs = prefs
    return prefs


def _format_number(value, decimals=2):
    prefs = _user_preferences()
    thousands, decimal = NUMBER_FORMATS.get(
        prefs.get("number_format", "1,234.56"), (",", ".")
    )
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    formatted = f"{number:,.{decimals}f}"
    if (thousands, decimal) != (",", "."):
        formatted = (
            formatted.replace(",", "\x00")
            .replace(".", decimal)
            .replace("\x00", thousands)
        )
    return formatted


def _format_money(value, decimals=2):
    prefs = _user_preferences()
    code = prefs.get("preferred_currency", "NPR")
    symbol = CURRENCY_SYMBOLS.get(code, code)
    return f"{symbol} {_format_number(value, decimals)}"


def _format_date(value):
    fmt = DATE_FORMATS.get(
        _user_preferences().get("date_format", "YYYY-MM-DD"), "%Y-%m-%d"
    )
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.strptime(value[:10], "%Y-%m-%d")
        except ValueError:
            return value
    return value.strftime(fmt)


def _format_month(value):
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.strptime(value[:7], "%Y-%m")
        except ValueError:
            return value
    return value.strftime("%B %Y")


app.jinja_env.filters["money"] = _format_money
app.jinja_env.filters["fmt_date"] = _format_date
app.jinja_env.filters["fmt_month"] = _format_month


def _validate_category_name(name):
    """Validate a custom category/income-source name. Returns a list of errors."""
    errors = []
    if not name:
        errors.append("Category name is required")
    elif len(name) > CUSTOM_CATEGORY_MAX_LENGTH:
        errors.append(f"Category name must be {CUSTOM_CATEGORY_MAX_LENGTH} characters or fewer")
    elif not CUSTOM_CATEGORY_PATTERN.match(name):
        errors.append("Category name can only contain letters, numbers and spaces")
    return errors


def _financial_month_range(today, start_day):
    """Return (start_date, end_date) for the financial month containing `today`."""
    start_day = max(1, min(28, start_day))
    if today.day >= start_day:
        start = today.replace(day=start_day)
    else:
        first_of_this_month = today.replace(day=1)
        prev_month_end = first_of_this_month - timedelta(days=1)
        start = prev_month_end.replace(day=min(start_day, prev_month_end.day))

    if start.month == 12:
        next_month_start = start.replace(year=start.year + 1, month=1)
    else:
        next_month_start = start.replace(month=start.month + 1)
    end = next_month_start - timedelta(days=1)
    return start, end


def resolve_category(form):
    """Return the effective category, resolving the custom-category sentinel."""
    category = form.get("category", "").strip()
    if category == CUSTOM_CATEGORY_SENTINEL:
        return form.get("custom_category", "").strip()
    return category


def validate_expense_form(form, valid_categories=None):
    """Validate expense form data. Returns a list of error strings."""
    if valid_categories is None:
        valid_categories = VALID_CATEGORIES
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
    elif category_choice not in valid_categories:
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

@app.route("/<filename>")
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
    return render_template("landing.html", current_month=datetime.now().strftime("%B %Y"))


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

        seed_default_categories(new_user["id"])

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
            seed_default_categories(user_id)

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
    export_format = get_user_preferences(g.user_id).get("default_export_format", "xlsx")

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
        export_format=export_format,
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

        errors = validate_expense_form(request.form, _user_expense_categories())

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
            expense=expense
        )

    # POST request
    expense = get_expense_by_id(id, g.user_id)
    if expense is None:
        # Not found or not owned by user
        return "", 404

    # Validate form data using the same validation as add_expense
    errors = validate_expense_form(request.form, _user_expense_categories())

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


def _validated_export_dates():
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    try:
        validated_from = datetime.strptime(date_from, "%Y-%m-%d").strftime("%Y-%m-%d") if date_from else None
        validated_to = datetime.strptime(date_to, "%Y-%m-%d").strftime("%Y-%m-%d") if date_to else None
    except ValueError:
        return None, None
    if validated_from and validated_to and validated_from > validated_to:
        return None, None
    return validated_from, validated_to


@app.route("/expenses/export")
def export_expenses():
    if not g.user_id:
        return redirect(url_for("login"))

    validated_from, validated_to = _validated_export_dates()
    template = request.args.get("template", DEFAULT_TEMPLATE)
    if template not in EXPORT_TEMPLATES:
        template = DEFAULT_TEMPLATE

    rows = get_expenses_for_export(g.user_id, validated_from, validated_to)
    workbook_bytes = build_expense_workbook(rows, template)

    filename = f"expenses_{template}_{date_obj.today().strftime('%Y-%m-%d')}.xlsx"
    return Response(
        workbook_bytes,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/expenses/export/pdf")
def export_expenses_pdf():
    if not g.user_id:
        return redirect(url_for("login"))

    user = get_user_by_id(g.user_id)
    if user is None:
        session.clear()
        return redirect(url_for("login"))

    validated_from, validated_to = _validated_export_dates()
    rows = get_expenses_for_export(g.user_id, validated_from, validated_to)
    stats = get_summary_stats(g.user_id, validated_from, validated_to)
    categories = get_category_breakdown(g.user_id, validated_from, validated_to)
    pdf_bytes = build_expense_pdf(
        rows, stats, categories, validated_from, validated_to, user["name"])

    filename = f"expenses_statement_{date_obj.today().strftime('%Y-%m-%d')}.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ------------------------------------------------------------------ #
# Profile & financial settings                                        #
# ------------------------------------------------------------------ #

@app.route("/settings")
def settings_home():
    if not g.user_id:
        return redirect(url_for("login"))
    return render_template("settings/index.html")


@app.route("/settings/categories", methods=["GET", "POST"])
def settings_categories():
    if not g.user_id:
        return redirect(url_for("login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        color = request.form.get("color", "").strip() or None

        errors = _validate_category_name(name)

        if errors:
            for error in errors:
                flash(error)
        else:
            try:
                create_category(g.user_id, name, "expense", color=color)
                flash("Category added.")
            except Exception as e:
                app.logger.error(f"Failed to create category: {e}")
                flash("A category with that name already exists for this type.")

        return redirect(url_for("settings_categories"))

    seed_default_categories(g.user_id)
    expense_categories = get_categories(g.user_id, type="expense", include_archived=True)
    return render_template(
        "settings/categories.html",
        expense_categories=expense_categories
    )


@app.route("/settings/categories/<int:id>/edit", methods=["POST"])
def settings_category_edit(id):
    if not g.user_id:
        return redirect(url_for("login"))

    name = request.form.get("name", "").strip()
    color = request.form.get("color", "").strip() or None

    errors = _validate_category_name(name)
    if errors:
        for error in errors:
            flash(error)
    else:
        try:
            updated = update_category(id, g.user_id, name, color=color)
            flash("Category updated." if updated else "Category not found.")
        except Exception as e:
            app.logger.error(f"Failed to update category: {e}")
            flash("A category with that name already exists for this type.")

    return redirect(url_for("settings_categories"))


@app.route("/settings/categories/<int:id>/archive", methods=["POST"])
def settings_category_archive(id):
    if not g.user_id:
        return redirect(url_for("login"))

    archived = request.form.get("archived") == "1"
    updated = set_category_archived(id, g.user_id, archived)
    if updated:
        flash("Category archived." if archived else "Category restored.")
    else:
        flash("Category not found.")

    return redirect(url_for("settings_categories"))


@app.route("/settings/categories/<int:id>/delete", methods=["POST"])
def settings_category_delete(id):
    if not g.user_id:
        return redirect(url_for("login"))

    result = delete_category(id, g.user_id)
    if result == "deleted":
        flash("Category deleted.")
    elif result == "in_use":
        flash("This category is used by existing expenses and cannot be deleted. Archive it instead.")
    else:
        flash("Category not found.")

    return redirect(url_for("settings_categories"))


@app.route("/settings/income", methods=["GET", "POST"])
def settings_income():
    if not g.user_id:
        return redirect(url_for("login"))

    if request.method == "POST":
        source = request.form.get("source", "").strip()
        amount_str = request.form.get("amount", "").strip()
        effective_month = request.form.get("effective_month", "").strip()

        errors = []
        if not source:
            errors.append("Income source is required")
        elif len(source) > CUSTOM_CATEGORY_MAX_LENGTH:
            errors.append(f"Income source must be {CUSTOM_CATEGORY_MAX_LENGTH} characters or fewer")

        try:
            amount = float(amount_str)
            if amount <= 0:
                errors.append("Amount must be greater than zero")
        except ValueError:
            errors.append("Amount must be a valid number")

        if not effective_month:
            errors.append("Effective month is required")
        else:
            try:
                datetime.strptime(effective_month, "%Y-%m")
            except ValueError:
                errors.append("Effective month must be in YYYY-MM format")

        if errors:
            for error in errors:
                flash(error)
        else:
            add_income_entry(g.user_id, source, float(amount_str), effective_month)
            flash("Income entry added.")

        return redirect(url_for("settings_income"))

    entries = get_income_entries(g.user_id)
    current_month = date_obj.today().strftime("%Y-%m")
    return render_template("settings/income.html", entries=entries, current_month=current_month)


@app.route("/settings/income/<int:id>/delete", methods=["POST"])
def settings_income_delete(id):
    if not g.user_id:
        return redirect(url_for("login"))

    if delete_income_entry(id, g.user_id):
        flash("Income entry removed.")
    else:
        flash("Income entry not found.")

    return redirect(url_for("settings_income"))


@app.route("/settings/budgets", methods=["GET", "POST"])
def settings_budgets():
    if not g.user_id:
        return redirect(url_for("login"))

    if request.method == "POST":
        scope = request.form.get("scope", "").strip()
        amount_str = request.form.get("monthly_limit", "").strip()

        try:
            monthly_limit = float(amount_str)
            if monthly_limit <= 0:
                raise ValueError
        except ValueError:
            flash("Budget amount must be a positive number")
            return redirect(url_for("settings_budgets"))

        if scope == "overall":
            set_overall_budget(g.user_id, monthly_limit)
        else:
            try:
                category_id = int(scope)
            except ValueError:
                flash("Invalid budget category")
                return redirect(url_for("settings_budgets"))
            set_category_budget(g.user_id, category_id, monthly_limit)

        flash("Budget saved.")
        return redirect(url_for("settings_budgets"))

    seed_default_categories(g.user_id)
    prefs = get_user_preferences(g.user_id)
    start, end = _financial_month_range(date_obj.today(), prefs["financial_month_start_day"])
    period_start, period_end = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    budgets = get_budgets(g.user_id)
    consumption = get_budget_consumption(g.user_id, period_start, period_end)
    expense_categories = get_categories(g.user_id, type="expense", include_archived=False)

    overall_budget = next((b for b in budgets if b["category_id"] is None), None)
    overall_spent = consumption["overall"]
    overall_pct = (
        round((overall_spent / overall_budget["monthly_limit"]) * 100) if overall_budget else None
    )

    category_rows = []
    for category in expense_categories:
        budget = next((b for b in budgets if b["category_id"] == category["id"]), None)
        spent = consumption["by_category"].get(category["name"], 0.0)
        limit = budget["monthly_limit"] if budget else None
        pct = round((spent / limit) * 100) if limit else None
        category_rows.append({
            "category": category,
            "limit": limit,
            "spent": spent,
            "pct": pct,
            "near_limit": pct is not None and pct >= BUDGET_WARNING_THRESHOLD,
            "is_over": pct is not None and pct >= 100,
        })

    return render_template(
        "settings/budgets.html",
        overall_budget=overall_budget,
        overall_spent=overall_spent,
        overall_pct=overall_pct,
        overall_near_limit=overall_pct is not None and overall_pct >= BUDGET_WARNING_THRESHOLD,
        overall_is_over=overall_pct is not None and overall_pct >= 100,
        category_rows=category_rows,
        period_start=period_start,
        period_end=period_end,
    )


@app.route("/settings/preferences", methods=["GET", "POST"])
def settings_preferences():
    if not g.user_id:
        return redirect(url_for("login"))

    if request.method == "POST":
        currency = request.form.get("preferred_currency", "").strip()
        try:
            start_day = int(request.form.get("financial_month_start_day", "1"))
        except ValueError:
            start_day = 1
        start_day = max(1, min(28, start_day))
        date_format = request.form.get("date_format", "").strip()
        number_format = request.form.get("number_format", "").strip()
        export_format = request.form.get("default_export_format", "").strip()

        errors = []
        if currency not in CURRENCY_CHOICES:
            errors.append("Please choose a valid currency")
        if date_format not in DATE_FORMAT_CHOICES:
            errors.append("Please choose a valid date format")
        if number_format not in NUMBER_FORMAT_CHOICES:
            errors.append("Please choose a valid number format")
        if export_format not in EXPORT_FORMAT_CHOICES:
            errors.append("Please choose a valid export format")

        if errors:
            for error in errors:
                flash(error)
        else:
            update_user_preferences(
                g.user_id, currency, start_day, date_format, number_format, export_format
            )
            flash("Preferences updated.")

        return redirect(url_for("settings_preferences"))

    prefs = get_user_preferences(g.user_id)
    return render_template(
        "settings/preferences.html",
        prefs=prefs,
        currency_choices=CURRENCY_CHOICES,
        date_format_choices=DATE_FORMAT_CHOICES,
        number_format_choices=NUMBER_FORMAT_CHOICES,
        export_format_choices=EXPORT_FORMAT_CHOICES,
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
