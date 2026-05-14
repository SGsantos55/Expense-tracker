# Spec: Registration

## Overview
Implements user registration functionality with email/password authentication. Users can create an account with a unique email and secure password. This is step 2 of the Spendly roadmap, building on the database foundation from step 1.

## Depends on
- Step 1: Database Setup (complete)

## Routes
- `GET /register` — Display registration form — public
- `POST /register` — Process registration form — public

## Database changes
None — users table already exists from step 1 (id, name, email, password_hash, created_at).

## Templates
- **Create:** None (register.html already exists)
- **Modify:** `templates/register.html` — Add form with name, email, password fields; Connect to POST endpoint

## Files to change
- `app.py` — Add registration POST handler with validation, password hashing, database insert

## Files to create
- None

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with `werkzeug.security.generate_password_hash`
- Validate: name not empty, email not empty + valid format, password min 6 chars
- Check email uniqueness before inserting
- Use Flask `request` object to get form data
- Use CSS variables — never hardcode hex values
- Template extends `base.html`

## Definition of done
- [ ] GET /register shows registration form with name, email, password fields
- [ ] POST /register validates input and shows errors for invalid data
- [ ] POST /register checks for duplicate email and shows error if exists
- [ ] Successful registration creates user in database with hashed password
- [ ] Successful registration redirects to login page with success message
- [ ] Form uses proper HTML5 validation attributes
- [ ] Error messages display inline or as flash messages