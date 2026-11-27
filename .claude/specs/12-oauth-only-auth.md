# Spec: OAuth-Only Authentication

## Overview
Expense Tracker currently supports two sign-in methods: email/password (with email
verification and password reset delivered over SMTP/Resend) and Google OAuth.
This feature removes the email/password path and everything that depends on
outbound email for authentication, leaving Google OAuth as the only way to
register and sign in. This removes the SMTP/Resend dependency (which already
fails on hosted environments), eliminates password storage, and simplifies the
auth surface now that the app is deployed to Vercel with a Neon database.

## Depends on
- Step 02 — Registration (users table)
- Step 03 — Login/Logout (session handling, `g.user_id`)
- Step 12 (existing) — Google OAuth (`/login/google`, `/login/google/callback`)
- Step 13 — SMTP for Authentication (the code being removed)
- Step 15 — Switch Database to PostgreSQL

## Routes
Removed:
- `POST /register` and `GET /register` — replaced by a redirect to `/login`
- `GET /verify/<token>`, `POST /verify/resend` — removed
- `GET/POST /password/forgot`, `GET/POST /password/reset/<token>` — removed

Changed:
- `GET /login` — public — renders only a "Continue with Google" button; no
  email/password form. Redirects to `/profile` if already logged in.
- `POST /login` — no longer accepted (405).
- `GET /register` — public — 302 redirect to `/login` (kept so existing links
  and bookmarks do not 404).

Unchanged:
- `GET /login/google`, `GET /login/google/callback` — public

No new routes.

## Database changes
- `users.password_hash` — no longer written. Keep the column (nullable) for
  now to avoid a destructive migration; new users insert without it.
- `users.email_verified` — Google-verified emails: `create_oauth_user` must set
  `email_verified = 1`. Keep the column.
- `auth_tokens` table — no longer used. Stop creating it in `init_db()`.
  Do not drop existing tables/data automatically; document a manual
  `DROP TABLE IF EXISTS auth_tokens;` in the spec's notes only.
- `seed_db()` — the demo user is seeded with `generate_password_hash('demo123')`;
  change it to seed with no password (`password_hash` NULL, `email_verified = 1`).

Verify against `database/db.py` before implementing.

## Templates
- **Create:** none
- **Modify:**
  - `templates/login.html` — remove the email/password form, "Forgot password?"
    link, unverified-email resend block; keep flash/error display and the
    Google button; remove the "Create one free" link to `/register` (replace
    with copy that Google creates the account on first sign-in).
  - `templates/register.html` — delete (route redirects to `/login`).
  - `templates/base.html` — nav "Get started" CTA points to `login` instead
    of `register`.
  - `templates/landing.html` — the three `url_for('register')` CTAs point to
    `url_for('login')`.
- **Delete:** `templates/auth/forgot_password.html`,
  `templates/auth/reset_password.html`, `templates/emails/verify_email.html`,
  `templates/emails/reset_password.html`

## Files to change
- `app.py` — remove `/verify/*`, `/password/*` routes, token helpers
  (`_hash_token`, `_issue_token`, `_send_verification`, `_send_password_reset`,
  TTL constants), the password branch of `/login`, the POST handler of
  `/register`; remove unused imports (`check_password_hash`,
  `generate_password_hash` if unused elsewhere, `hashlib`, `secrets`,
  `timedelta` if unused, mailer import, removed query functions).
- `database/queries.py` — remove `get_user_by_email_for_auth`,
  `set_email_verified`, `update_password_hash`, `create_auth_token`,
  `get_valid_auth_token`, `mark_token_used`; make `create_oauth_user` set
  `email_verified = 1`; also remove any `auth_tokens` cleanup in
  `delete_user` only if it no longer applies (keep deletion of existing rows
  safe if the table still exists).
- `database/db.py` — stop creating `auth_tokens`; update demo seed user.
- `.env.example` — remove `RESEND_API_KEY`, `MAIL_FROM`, `MAIL_SERVER`,
  `MAIL_PORT`, `MAIL_USE_TLS`, `MAIL_USERNAME`, `MAIL_PASSWORD`; keep
  `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `ADMIN_EMAIL`.
- `render.yaml` — remove mail env var entries if present.
- `CLAUDE.md` — update route list and notes (no password auth, no email).
- `tests/` — update or remove tests that exercise `/register`, password
  login, verification and reset.

## Files to create
- `tests/test_oauth_only_auth.py` — route-level tests (see Definition of done).

## Files to delete
- `database/mailer.py`
- `templates/register.html`
- `templates/auth/forgot_password.html`, `templates/auth/reset_password.html`
- `templates/emails/verify_email.html`, `templates/emails/reset_password.html`

## New dependencies
No new dependencies. `requests` stays only if used elsewhere; remove it from
`requirements.txt` only if nothing else imports it (Authlib's httpx/requests
needs must be checked first).

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug — no new password storage is introduced; any
  remaining legacy `password_hash` values are never read for login
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Google OAuth config stays in `OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET`;
  the app must start cleanly with all mail env vars unset
- Existing users who registered with a password must still be able to sign
  in via Google when the Google account email matches (the existing
  match-by-email linking in the callback stays)
- Contact form and admin messages must keep working (they do not use the mailer)
- Preserve `session["user_id"]` and `g.user_id` behaviour for all other routes

## Definition of done
- [ ] `GET /login` shows a "Continue with Google" button and no email/password
      fields, no "Forgot password?" link
- [ ] `POST /login` returns 405
- [ ] `GET /register` redirects (302) to `/login`; `POST /register` is not an
      account-creation path
- [ ] `/verify/<token>`, `/verify/resend`, `/password/forgot`,
      `/password/reset/<token>` return 404
- [ ] Clicking "Continue with Google" redirects to Google's consent screen
- [ ] A successful Google callback with a new email creates a user with
      `email_verified = 1`, seeds default categories, and lands on `/profile`
- [ ] A Google callback with an email matching an existing password-based user
      links `google_id` and signs in that same user
- [ ] A failed or denied Google callback flashes an error and returns to `/login`
- [ ] Landing page and nav CTAs lead to `/login`
- [ ] App starts and all pages render with `RESEND_API_KEY` and `MAIL_*` unset
- [ ] `grep -rn "smtplib\|resend\|send_verification_email" --include=*.py .`
      (excluding venv) returns nothing
- [ ] Fresh database: `init_db()` does not create `auth_tokens`; `seed_db()`
      creates the demo user without a password
- [ ] `pytest` passes with the updated test suite
- [ ] Deployed Vercel site: Google redirect URI
      `https://expense-tracker-five-beryl-26.vercel.app/login/google/callback`
      is added in Google Cloud Console and sign-in works end to end
