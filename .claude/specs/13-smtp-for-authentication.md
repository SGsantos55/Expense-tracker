# Spec: SMTP for Authentication

## Overview
This feature wires real email delivery into Spendly's authentication flows using
SMTP, so the app can prove a user controls their email address and let users
recover a lost password. It adds (1) email verification on registration — a new
user receives a one-time, time-limited verification link and stays unverified
until they click it — and (2) a self-service password reset flow — a user
requests a reset, receives a one-time, time-limited link by email, and sets a
new password. At this stage of the roadmap email/password auth, Google OAuth,
profile, and full expense CRUD are all complete, so hardening the account
lifecycle with verified emails and password recovery is the natural next
authentication enhancement. SMTP settings are read from environment variables
and the sender is implemented as a small reusable module so no credentials are
hardcoded.

## Depends on
- Step 02 — Registration (users table + user creation)
- Step 03 — Login/Logout (session handling, `g.user_id`, logout)
- Step 12 — Google OAuth (nullable `password_hash`, `google_id`; OAuth-only
  users must be excluded from password-reset/verification paths)

## Routes
- `GET /verify/<token>` — consumes an email-verification token, marks the user's
  email verified, and redirects to `/login` with a flash — public.
- `POST /verify/resend` — re-sends a verification email to the logged-in (or
  just-registered) unverified user; throttled — public.
- `GET /password/forgot` — renders the "forgot password" request form — public.
- `POST /password/forgot` — accepts an email, and if a matching password-based
  account exists generates a reset token and emails the reset link; always shows
  the same generic confirmation to avoid account enumeration — public.
- `GET /password/reset/<token>` — validates the reset token and renders the
  "set new password" form (404/invalid message on bad or expired token) —
  public.
- `POST /password/reset/<token>` — validates the token, updates the password
  hash, invalidates the token, and redirects to `/login` — public.

## Database changes
Verify against `database/db.py` before implementing. Current `users` has
`password_hash TEXT` (nullable) and `google_id TEXT UNIQUE`; there is no
verification or token storage. Changes:
- Add `email_verified INTEGER NOT NULL DEFAULT 0` to `users`.
- Create a new table `auth_tokens`:
  - `id INTEGER PRIMARY KEY AUTOINCREMENT`
  - `user_id INTEGER NOT NULL` (FK → `users(id)`)
  - `token_hash TEXT NOT NULL` — store only a hash of the token, never the raw
    token
  - `purpose TEXT NOT NULL` — `'verify_email'` or `'password_reset'`
  - `expires_at TEXT NOT NULL`
  - `used_at TEXT` — NULL until consumed (single-use)
  - `created_at TEXT DEFAULT (datetime('now'))`
  - `FOREIGN KEY (user_id) REFERENCES users(id)`
  - `CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_tokens_hash ON auth_tokens(token_hash)`
- Because `init_db()` uses `CREATE TABLE IF NOT EXISTS`, update the fresh-DB
  `users` definition AND add an idempotent migration for existing databases:
  guard an `ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0`
  with a `PRAGMA table_info(users)` check, and create `auth_tokens` with
  `CREATE TABLE IF NOT EXISTS`.
- `seed_db()`: mark the seeded demo user as `email_verified = 1` so local login
  keeps working.

## Templates
- **Create:**
  - `templates/auth/forgot_password.html` — email-entry form.
  - `templates/auth/reset_password.html` — new-password form (password +
    confirm).
  - `templates/emails/verify_email.html` — HTML body for the verification email.
  - `templates/emails/reset_password.html` — HTML body for the reset email.
- **Modify:**
  - `templates/login.html` — add a "Forgot password?" link to `/password/forgot`
    and show a resend-verification prompt when login is blocked by an unverified
    account.
  - `templates/register.html` — after successful registration, surface the
    "check your email to verify" message (via flash).

## Files to change
- `database/db.py` — add `email_verified` to `users` CREATE TABLE + migration,
  add `auth_tokens` table + index, and verify the demo user in `seed_db()`.
- `database/queries.py` — add helpers:
  `set_email_verified(user_id)`,
  `get_user_by_email_for_auth(email)` (returns id, password_hash, email_verified,
  google_id),
  `create_auth_token(user_id, token_hash, purpose, expires_at)`,
  `get_valid_auth_token(token_hash, purpose)` (unused + unexpired),
  `mark_token_used(token_id)`,
  `update_password_hash(user_id, password_hash)`.
- `app.py` — add the verify/resend and forgot/reset routes; after registration,
  create a `verify_email` token and send the email; block password login for
  unverified password-based users (allow OAuth/verified users through); read
  `APP_BASE_URL` for building absolute links.
- `templates/login.html`, `templates/register.html` — see Templates.
- `static/css/style.css` — styles for the new auth forms/links using existing
  CSS variables only.
- `requirements.txt` — no change if standard-library `smtplib`/`email` are used
  (preferred); otherwise add the chosen mailer.
- `.env.example` — document the new SMTP/base-url variables (no real secrets).

## Files to create
- `auth/mailer.py` (or `services/mailer.py`) — a small, framework-light module
  that reads SMTP config from the environment and exposes
  `send_email(to, subject, html_body, text_body=None)` plus thin helpers
  `send_verification_email(...)` and `send_password_reset_email(...)`. Uses the
  standard library `smtplib` + `email.message.EmailMessage` and supports
  STARTTLS/SSL based on config.
- `templates/auth/forgot_password.html`
- `templates/auth/reset_password.html`
- `templates/emails/verify_email.html`
- `templates/emails/reset_password.html`

## New dependencies
No new pip packages — use the Python standard library (`smtplib`, `ssl`,
`email.message`, `secrets`, `hashlib`) for sending and token generation.

## Rules for implementation
- No SQLAlchemy or ORMs — use `sqlite3` via `get_db()`.
- Parameterised queries only — never string-format user input into SQL.
- Passwords hashed with werkzeug (`generate_password_hash` /
  `check_password_hash`); the reset flow must re-hash the new password.
- Use CSS variables — never hardcode hex values.
- All page templates extend `base.html` (email templates are standalone HTML and
  do not extend `base.html`).
- **Never hardcode SMTP credentials or the base URL** — read them from
  environment variables via `python-dotenv` (already in use):
  `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`,
  `SMTP_FROM`, and `APP_BASE_URL`.
- Tokens: generate with `secrets.token_urlsafe(32)`; store only
  `hashlib.sha256(token).hexdigest()` in `auth_tokens`; links carry the raw
  token. Tokens are single-use (`used_at`) and time-limited (verification ~24h,
  reset ~1h).
- Prevent account enumeration: `/password/forgot` always returns the same
  generic success message whether or not the email exists, and never sends to
  OAuth-only accounts (no password to reset).
- OAuth-only users (`password_hash IS NULL`) are considered email-verified
  implicitly and must be excluded from the password-reset path.
- Fail safe on email errors: if SMTP sending raises, log the error, do not leak
  details to the user, and (for registration) still create the account but
  inform the user verification email could not be sent and can be resent.
- Do not block the password-login check with a raw SQL string; reuse the
  parameterised query helpers.

## Definition of done
- `.env.example` documents `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`,
  `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_FROM`, and `APP_BASE_URL`; the app
  starts with these read from the environment and nothing hardcoded.
- Registering a new user inserts a `users` row with `email_verified = 0` and
  creates one `auth_tokens` row with `purpose = 'verify_email'`, and a
  verification email is sent (verifiable via a local SMTP debug server such as
  `python -m aiosmtpd -n -l localhost:1025`).
- Clicking the verification link flips `email_verified` to `1`, marks the token
  `used_at`, and the link cannot be reused (shows an invalid/expired message).
- A password-based user who is not verified cannot complete email/password login
  and is offered a "resend verification" action; after verifying, login
  succeeds.
- `POST /password/forgot` with a known password account creates a
  `purpose = 'password_reset'` token and sends a reset email; with an unknown or
  OAuth-only email it sends nothing but shows the same generic confirmation.
- The reset link renders the new-password form; submitting a valid new password
  updates `password_hash`, marks the token used, and lets the user log in with
  the new password.
- Expired or already-used verify/reset tokens are rejected with a clear message
  and never mutate account state.
- `pip install -r requirements.txt` still succeeds with no new dependencies
  required.
- Existing databases migrate cleanly on startup (no errors; `email_verified`
  column and `auth_tokens` table present) and the seeded demo user is
  `email_verified = 1`.
