import os
import psycopg
from psycopg.rows import dict_row
from werkzeug.security import generate_password_hash

from database.defaults import DEFAULT_EXPENSE_CATEGORIES

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql:///spendly")


def get_db():
    """Returns a PostgreSQL connection with dict rows (row['col'] access)."""
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db():
    """Creates all tables using CREATE TABLE IF NOT EXISTS."""
    conn = get_db()
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT,
                google_id TEXT UNIQUE,
                email_verified SMALLINT NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (now()::text)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS expenses (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL DEFAULT (now()::text),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS contact_messages (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                subject TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (now()::text)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS auth_tokens (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL,
                purpose TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT NOT NULL DEFAULT (now()::text),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_tokens_hash ON auth_tokens(token_hash)'
        )
        conn.execute('''
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('expense', 'income')),
                icon TEXT,
                color TEXT,
                is_archived SMALLINT NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (now()::text),
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE (user_id, name, type)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS income_entries (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                effective_month TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (now()::text),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS budgets (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                category_id INTEGER,
                monthly_limit DOUBLE PRECISION NOT NULL,
                created_at TEXT NOT NULL DEFAULT (now()::text),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (category_id) REFERENCES categories(id)
            )
        ''')
        _run_migrations(conn)
        conn.commit()
    finally:
        conn.close()


def _run_migrations(conn):
    """Idempotent migrations for databases created before this schema."""
    conn.execute(
        'ALTER TABLE users ADD COLUMN IF NOT EXISTS '
        'email_verified SMALLINT NOT NULL DEFAULT 0'
    )
    conn.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "preferred_currency TEXT NOT NULL DEFAULT 'NPR'"
    )
    conn.execute(
        "ALTER TABLE users ALTER COLUMN preferred_currency SET DEFAULT 'NPR'"
    )
    conn.execute(
        'ALTER TABLE users ADD COLUMN IF NOT EXISTS '
        'financial_month_start_day SMALLINT NOT NULL DEFAULT 1'
    )
    conn.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "date_format TEXT NOT NULL DEFAULT 'YYYY-MM-DD'"
    )
    conn.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "number_format TEXT NOT NULL DEFAULT '1,234.56'"
    )
    conn.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "default_export_format TEXT NOT NULL DEFAULT 'xlsx'"
    )


def seed_db():
    """Inserts sample data for development if not already present."""
    conn = get_db()
    try:
        existing = conn.execute('SELECT COUNT(*) AS count FROM users').fetchone()
        if existing['count'] > 0:
            return

        password_hash = generate_password_hash('demo123')
        row = conn.execute(
            'INSERT INTO users (name, email, password_hash, email_verified) '
            'VALUES (%s, %s, %s, 1) RETURNING id',
            ('Demo User', 'plankmax05@gmail.com', password_hash)
        ).fetchone()
        user_id = row['id']

        expenses = [
            (user_id, 45.50, 'Food', '2026-05-02', 'Lunch with friends'),
            (user_id, 25.00, 'Transport', '2026-05-04', 'Bus fare to campus'),
            (user_id, 120.00, 'Bills', '2026-05-05', 'Internet bill'),
            (user_id, 35.00, 'Health', '2026-05-07', 'Pharmacy'),
            (user_id, 15.99, 'Entertainment', '2026-05-09', 'Netflix subscription'),
            (user_id, 89.99, 'Shopping', '2026-05-11', 'New headphones'),
            (user_id, 22.50, 'Food', '2026-05-12', 'Groceries'),
            (user_id, 10.00, 'Other', '2026-05-13', 'Miscellaneous'),
        ]

        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO categories (user_id, name, type, color) "
                "VALUES (%s, %s, 'expense', %s)",
                [(user_id, name, color) for name, color in DEFAULT_EXPENSE_CATEGORIES]
            )
            cur.executemany(
                'INSERT INTO expenses (user_id, amount, category, date, description) '
                'VALUES (%s, %s, %s, %s, %s)',
                expenses
            )
        conn.commit()
    finally:
        conn.close()
