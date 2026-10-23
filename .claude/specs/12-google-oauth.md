# Spec: Google OAuth Login

## Overview
This feature lets users sign in to Spendly with their Google account instead of
(or in addition to) an email/password. It adds a "Continue with Google" button
to the login and registration pages, runs the OAuth 2.0 Authorization Code flow
against Google, and on success creates or matches a local user record and logs
them in via the existing session mechanism. At this stage of the roadmap the
email/password auth, profile, and full expense CRUD are complete, so social
login lowers signup friction and is the natural next authentication
enhancement.

## Depends on
- Step 02 — Registration (users table + user creation)
- Step 03 — Login/Logout (session handling, `g.user_id`, logout)

## Routes
- `GET /login/google` — starts the Google OAuth flow; redirects the user to
  Google's consent screen — public.
- `GET /login/google/callback` — Google redirects back here with an auth code;
  exchanges it for tokens, fetches the user's profile, creates/matches the local
  user, sets the session, and redirects to `/profile` — public.

(The registered Authorized redirect URI in Google Cloud Console is
`http://localhost:5001/login/google/callback` for local development.)

## Database changes
The existing `users` table (`database/db.py`) has `password_hash TEXT NOT NULL`
and no OAuth columns. Changes:
- Add `google_id TEXT UNIQUE` to `users` to link a Google account to a local
  user (stores Google's stable `sub` claim).
- Allow `password_hash` to be **nullable** so OAuth-only users (who have no
  password) can be stored.
- Since `init_db()` uses `CREATE TABLE IF NOT EXISTS`, update the `CREATE TABLE`
  definition for fresh databases AND add an idempotent migration for existing
  databases: `ALTER TABLE users ADD COLUMN google_id TEXT` guarded by a check of
  `PRAGMA table_info(users)` (SQLite cannot add a UNIQUE column via ALTER, so
  enforce uniqueness in application logic and/or a `CREATE UNIQUE INDEX IF NOT
  EXISTS idx_users_google_id ON users(google_id)`). To make `password_hash`
  nullable on an existing table, rebuild via the standard SQLite pattern
  (create new table, copy, drop, rename) inside the migration.

## Templates
- **Create:** none
- **Modify:**
  - `templates/login.html` — add a "Continue with Google" button linking to
    `/login/google`, visually separated from the email/password form.
  - `templates/register.html` — add the same "Continue with Google" button.

## Files to change
- `database/db.py` — update `users` CREATE TABLE (nullable `password_hash`,
  `google_id` column + unique index) and add the idempotent migration.
- `database/queries.py` — add helpers: `get_user_by_google_id(google_id)`,
  `get_user_by_email(email)` (if not reusable), and
  `create_oauth_user(name, email, google_id)`.
- `app.py` — register the Authlib OAuth client (configured from env vars) and
  add the `/login/google` and `/login/google/callback` routes.
- `templates/login.html`, `templates/register.html` — add the Google button.
- `static/css/style.css` — add a `.btn-google` / divider style using existing
  CSS variables only.
- `requirements.txt` — add `Authlib`.
- `.env` (not committed) — add `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.

## Files to create
- No new Python modules required. (OAuth client config lives in `app.py`.)

## New dependencies
- `Authlib` — OAuth 2.0 / OpenID Connect client for the Google flow.

## Rules for implementation
- No SQLAlchemy or ORMs — use `sqlite3` via `get_db()`.
- Parameterised queries only — never string-format user input into SQL.
- Passwords hashed with werkzeug (unchanged for password users; OAuth users
  store `NULL` password_hash and must not be able to log in via the password
  form).
- Use CSS variables — never hardcode hex values (Google button + divider).
- All templates extend `base.html`.
- **Never hardcode the client ID/secret** — read them from environment
  variables via `python-dotenv` (already in use), e.g.
  `os.environ["GOOGLE_CLIENT_ID"]`.
- Use Authlib's OpenID Connect discovery
  (`server_metadata_url=https://accounts.google.com/.well-known/openid-configuration`)
  and request the `openid email profile` scopes.
- Validate state/nonce via Authlib's built-in CSRF protection (do not implement
  a custom flow).
- Account linking: if a user with the Google email already exists, link by
  setting their `google_id`; otherwise create a new OAuth user. Match on
  `google_id` first, then fall back to `email`.
- Reuse the existing session pattern (`session["user_id"] = user_id`) and the
  existing `/logout` route — no changes to logout needed.

## Definition of done
- `pip install -r requirements.txt` installs `Authlib` without error.
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` are read from the environment; the
  app starts without them hardcoded anywhere.
- The login and register pages show a working "Continue with Google" button.
- Clicking it redirects to Google's consent screen.
- After granting consent, Google redirects to
  `http://localhost:5001/login/google/callback`, a local user is created (or
  matched), the session is set, and the user lands on `/profile`.
- A brand-new Google user results in exactly one new `users` row with a
  populated `google_id` and `NULL` password_hash.
- Signing in again with the same Google account reuses the existing row (no
  duplicate users).
- An existing email/password user who signs in with Google (same email) is
  linked to their existing account (no duplicate row).
- OAuth-only users cannot authenticate through the email/password form.
- `/logout` clears the session for OAuth-logged-in users as normal.
