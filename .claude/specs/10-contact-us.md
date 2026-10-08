# Spec: Contact Us Page

## Overview
Step 10 adds a public "Contact Us" page so visitors and users can send a message
to the Spendly team without needing an account. The page lives at `/contact` and
is reachable from the footer (alongside Terms and Privacy). It renders a simple
form (name, email, subject, message) that POSTs back to `/contact`. On submit the
handler validates the input server-side, stores the submission in a new
`contact_messages` table via a parameterised query, flashes a success message, and
redirects back to `/contact`. On validation failure it re-renders the form with the
error list and the previously entered values preserved. This gives Spendly a
lightweight support channel and a persisted record of inbound messages, while
following the same static-page + CSS-variable conventions already used by the
terms and privacy pages.

## Depends on
- Step 1: Database setup (`database/db.py`, `get_db()`, `init_db()` exist)
- The base template (`templates/base.html`) and footer link structure already exist

No login is required — this is a public page.

## Routes
- `GET /contact` — render the contact form — public
- `POST /contact` — validate input, store the message, flash success, redirect to `/contact` — public
- `GET /admin/messages` — list all contact submissions (newest first) — admin only (single admin by email); non-admins and logged-out visitors receive 404

## Database changes
Add one new table in `database/db.py` `init_db()` (using `CREATE TABLE IF NOT EXISTS`):

```sql
CREATE TABLE IF NOT EXISTS contact_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    subject TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
```

No changes to existing `users` or `expenses` tables. No new columns on existing tables.

## Templates
- **Create:** `templates/contact.html`
  - Extends `base.html`.
  - Sets `title`, `meta_description`, and a `{% block head %}` with a scoped `<style>`
    block that uses **CSS variables only**. Reuses existing auth/form classes
    (`.auth-section`, `.auth-card`, `.form-group`, `.form-input`, `.btn-submit`,
    `.auth-error`, `.auth-success`) plus a small `textarea.form-input` rule.
  - Renders a `<form method="POST" action="{{ url_for('contact') }}">` with fields:
    `name`, `email`, `subject`, `message` (textarea), and a submit button.
  - Displays flashed success messages (via `get_flashed_messages`) and the
    `errors` list when present.
  - Repopulates field values from variables passed back on validation failure
    (e.g. `value="{{ name }}"`).
- **Create:** `templates/admin/messages.html`
  - Extends `base.html`; scoped `<style>` in `{% block head %}` using CSS variables only.
  - Renders a table of all submissions (date, name, email, subject, message), newest
    first, with an empty-state message when there are none.
- **Modify:** `templates/base.html`
  - Add a `<a href="{{ url_for('contact') }}">Contact Us</a>` link to the
    `.footer-links` block, next to the existing Terms and Privacy links.

## Files to change
- `app.py`
  - Import `abort` from flask and `insert_contact_message`, `get_all_contact_messages`
    from `database.queries`.
  - Load environment variables via `python-dotenv` (`load_dotenv()`) and read
    `ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")` near the top. The real value
    lives in a gitignored `.env` file (never committed); `.env.example` documents it.
  - Add the `contact()` view handling `GET` and `POST` at `/contact`.
  - Server-side validation collecting an `errors` list: `name` required,
    `email` required and contains `@`, `subject` required, `message` required.
  - On success: call `insert_contact_message(...)`, `flash(...)` a success message,
    and `redirect(url_for("contact"))`.
  - On failure: `render_template("contact.html", errors=errors, name=..., email=...,
    subject=..., message=...)`.
  - Add the `admin_messages()` view at `/admin/messages`: `abort(404)` unless a user is
    logged in and their email equals `ADMIN_EMAIL`; otherwise render the list via
    `get_all_contact_messages()`.
- `database/db.py`
  - Add the `contact_messages` `CREATE TABLE IF NOT EXISTS` statement inside `init_db()`.
- `database/queries.py`
  - Add `insert_contact_message(name, email, subject, message)` — parameterised
    `INSERT INTO contact_messages (...) VALUES (?, ?, ?, ?)`; commits and closes.
  - Add `get_all_contact_messages()` — `SELECT ... FROM contact_messages
    ORDER BY created_at DESC, id DESC`; returns all rows.
- `templates/base.html`
  - Add the footer "Contact Us" link.

## Files to create
- `templates/contact.html`
- `templates/admin/messages.html`
- `.claude/specs/10-contact-us.md` (this spec)

## New dependencies
- `python-dotenv` — loads `ADMIN_EMAIL` (and any future secrets) from a gitignored `.env` file.

## Rules for implementation
- No SQLAlchemy or ORMs — raw `sqlite3` only via `get_db()`
- Parameterised queries only — never string-format values into SQL
- Passwords hashed with werkzeug (N/A here, but no plaintext secrets anywhere)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- `/contact` must be fully public — no `g.user_id` / login guard on either method
- `/admin/messages` is restricted to the single admin account (email == `ADMIN_EMAIL`,
  loaded from the environment / `.env`); non-admin and logged-out requests must return **404**
- Never hardcode the admin email (or other secrets) in source — read from the environment;
  keep `.env` gitignored and provide `.env.example` as a template
- Validate all four fields server-side; never trust client input
- `POST /contact` uses the Post/Redirect/Get pattern on success
- Strip whitespace from submitted values before validation/storage
- Reuse existing CSS variables and styling — no new inline styles
  (scoped `<style>` in `{% block head %}` is acceptable, matching `terms.html`)

## Definition of done
- [ ] `GET /contact` returns 200 for both logged-out and logged-in visitors and shows the form
- [ ] The footer on every page shows a "Contact Us" link that routes to `/contact`
- [ ] Submitting the form with all fields valid inserts one row into `contact_messages`,
      shows a success flash message, and redirects back to `/contact` (302 → 200)
- [ ] Submitting with any required field empty (or an email without `@`) re-renders the
      form with a visible error list and does **not** insert a row
- [ ] Previously entered values are preserved in the form after a validation error
- [ ] `contact_messages` table is created automatically on app startup via `init_db()`
- [ ] `GET /admin/messages` as the admin user (email == `ADMIN_EMAIL`) returns 200 and lists
      all messages newest-first
- [ ] `GET /admin/messages` logged-out or as a non-admin user returns 404
- [ ] No hardcoded hex colours are introduced; the pages use existing CSS variables
- [ ] `contact.html` and `admin/messages.html` extend `base.html` and render within the
      standard nav/footer layout
