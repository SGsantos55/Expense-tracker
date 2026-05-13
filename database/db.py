import sqlite3
import os
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'expense_tracker.db')


def get_db():
    """Returns a SQLite connection with row_factory and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Creates all tables using CREATE TABLE IF NOT EXISTS."""
    conn = get_db()
    try:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL,
                description TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.commit()
    finally:
        conn.close()


def seed_db():
    """Inserts sample data for development if not already present."""
    conn = get_db()
    try:
        existing = conn.execute('SELECT COUNT(*) as count FROM users').fetchone()
        if existing['count'] > 0:
            return

        password_hash = generate_password_hash('demo123')
        cursor = conn.execute(
            'INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)',
            ('Demo User', 'demo@spendly.com', password_hash)
        )
        user_id = cursor.lastrowid

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

        conn.executemany(
            'INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)',
            expenses
        )
        conn.commit()
    finally:
        conn.close()