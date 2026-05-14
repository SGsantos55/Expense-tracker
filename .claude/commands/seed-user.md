# Create a Single Dummy User in the Database

## Allowed Tools
- `Read`
- `Bash(python3:*)`

## Task

1. **Read `database/db.py`** to understand:
   - The `users` table schema
   - The `get_db()` helper function

2. **Write and run a Python script** using Bash that:

   - **Generates a realistic random Indian user** (using knowledge of common Indian names across regions):
     - **Name**: Realistic Indian first + last name
     - **Email**: Derived from the name with a random 2-3 digit number suffix  
       (e.g., `rahul.sharma91@gmail.com`)
     - **Password**: `"password123"` hashed with `werkzeug's generate_password_hash`
     - **created_at**: Current datetime

   - **Checks** if the generated email already exists in the `users` table.  
     If it does, regenerate until unique.

   - **Inserts** the user into the database using the same `get_db()` pattern found in `db.py`.

   - **Prints confirmation** with:
     - `id`
     - `name`
     - `email`


