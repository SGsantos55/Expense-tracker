# Spec: Login and Logout

## Overview
Implements user authentication with login and logout functionality. Users can log in with their email and password, and log out securely. This is step 3 of the Spendly roadmap, building on the registration feature from step 2.

## Depends on
- Step 2: Registration (complete)

## Routes
- `POST /login` — Process login credentials — public
- `GET /logout` — Clear session and redirect — logged-in users

## Database changes
No database changes — users table already exists from step 1.

## Templates
- **Create:** None
- **Modify:** `templates/login.html` — Add login form with email and password fields, connect to POST endpoint

## Files to change
- `app.py` — Add login POST handler, implement logout, add session management
- `templates/login.html` — Add form with email and password inputs, POST method

## Files to create
- None

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Password verification with `werkzeug.security.check_password_hash`
- Use Flask sessions for authentication (app.secret_key already set)
- Store user_id in session after successful login
- Clear entire session on logout
- Validate: email not empty, password not empty
- Show error for invalid credentials (don't reveal if email exists)
- Use `@app.before_request` to protect routes that require login
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`

## Definition of done
- [ ] GET /login shows login form with email and password fields
- [ ] POST /login validates input and shows errors for invalid data
- [ ] POST /login verifies credentials against database
- [ ] Successful login stores user_id in session and redirects to profile
- [ ] Failed login shows "Invalid email or password" error
- [ ] GET /logout clears session and redirects to landing page
- [ ] Session persists across requests (user stays logged in)
- [ ] Protected routes redirect to login when not authenticated