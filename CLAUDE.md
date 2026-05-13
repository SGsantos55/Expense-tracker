# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Flask-based expense tracker web application called "Spendly". It's a student project with placeholder routes for future implementation steps.

## Common Commands

```bash
# Run the development server
python app.py

# Run tests
pytest

# Run with specific test file
pytest -v test_file.py

# Activate virtual environment
source venv/bin/activate
```

The app runs on port 5001 with debug mode enabled (`app.run(debug=True, port=5001)`).

## Architecture

### Technology Stack
- **Framework**: Flask 3.1.3
- **Database**: SQLite (file: `expense_tracker.db`)
- **Testing**: pytest with pytest-flask
- **Templating**: Jinja2 (built into Flask)

### Directory Structure

```
expense-tracker/
├── app.py              # Main Flask application & routes
├── database/
│   └── db.py          # Database utilities (placeholder - implement get_db, init_db, seed_db)
├── templates/         # Jinja2 HTML templates
│   ├── base.html     # Base template with nav & footer
│   ├── landing.html   # Homepage
│   ├── login.html     # Login page
│   ├── register.html  # Registration page
│   ├── terms.html     # Terms & conditions
│   └── privacy.html   # Privacy policy
└── static/
    ├── css/style.css  # Main stylesheet (12KB)
    └── js/main.js     # JavaScript file
```

### Route Structure (app.py)

- `/` - Landing page
- `/register` - Registration
- `/login` - Login
- `/terms` - Terms & conditions
- `/privacy` - Privacy policy
- `/logout` - Logout (placeholder)
- `/profile` - Profile (placeholder)
- `/expenses/add` - Add expense (placeholder)
- `/expenses/<int:id>/edit` - Edit expense (placeholder)
- `/expenses/<int:id>/delete` - Delete expense (placeholder)

### Database Module (database/db.py)

This module needs to be implemented with:
- `get_db()` - Returns SQLite connection with row_factory and foreign keys enabled
- `init_db()` - Creates tables with CREATE TABLE IF NOT EXISTS
- `seed_db()` - Inserts sample development data

## Key Implementation Details

- The base template uses DM Serif Display and DM Sans fonts from Google Fonts
- CSS uses CSS variables for theming (e.g., `--neon-green`)
- The brand icon is ◈ (diamond character)
- Database file is gitignored (`expense_tracker.db`)

## Testing

Tests should be placed in the root or a `tests/` directory. Use pytest-flask to test Flask routes.