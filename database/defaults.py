"""Shared built-in category definitions.

Kept dependency-free so both the schema/seed layer (``database.db``) and the
settings query layer (``database.settings_queries``) can import it without
creating a circular import.
"""

DEFAULT_EXPENSE_CATEGORIES = [
    ("Food", "#00C47A"),
    ("Transport", "#12B5B0"),
    ("Bills", "#4F86F7"),
    ("Health", "#F2A93B"),
    ("Entertainment", "#9B6BFF"),
    ("Shopping", "#EF6F6C"),
    ("Other", "#8A94A6"),
]
