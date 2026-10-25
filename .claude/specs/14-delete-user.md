---
# Spec: Delete User

## Overview
Allows a logged-in user to permanently delete their account. This is a critical privacy feature that ensures users have control over their personal data. When a user is deleted, all their associated expenses and authentication tokens must also be removed to maintain database integrity and privacy.

## Depends on
- Registration and Login (User accounts must exist)
- Profile (User must be able to navigate to their account settings)

## Routes
- `POST /profile/delete` — Permanently deletes the current logged-in user's account and all associated data — logged-in

## Database changes
No new tables are required. However, the following changes are necessary to ensure data integrity:
- The `expenses` table already has a foreign key to `users(id)`. We must ensure that deletions are handled correctly. If `ON DELETE CASCADE` is not present, we must manually delete related data or modify the schema.
- Verification of `database/db.py` shows `PRAGMA foreign_keys = ON` is enabled, but the current `expenses` and `auth_tokens` tables do not specify `ON DELETE CASCADE`.

## Templates
- **Modify:** `templates/profile.html` — Add a "Delete Account" section with a confirmation warning and a form that posts to `/profile/delete`.

## Files to change
- `app.py` — Implement the `/profile/delete` route.
- `database/queries.py` — Add a `delete_user` function to handle the deletion of the user and their associated data.
- `templates/profile.html` — Add the UI for account deletion.

## Files to create
No new files.

## New dependencies
No new pip packages.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only
- Passwords hashed with werkzeug
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- The deletion must be permanent and irreversible.
- The user must be logged out immediately after account deletion.
- All related data (expenses, auth tokens) must be deleted before or alongside the user.

## Definition of done
- [ ] A "Delete Account" button/link exists on the profile page.
- [ ] Clicking the button triggers a confirmation (e.g., via a simple JS confirm or a separate confirmation step).
- [ ] Posting to `/profile/delete` successfully removes the user from the `users` table.
- [ ] All expenses associated with the deleted user are removed from the `expenses` table.
- [ ] All authentication tokens associated with the deleted user are removed from the `auth_tokens` table.
- [ ] The user is redirected to the landing page and their session is cleared.
- [ ] Attempting to access `/profile` after deletion redirects to `/login`.
---
