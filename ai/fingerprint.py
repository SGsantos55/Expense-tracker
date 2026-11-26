"""Canonical fingerprint for cached AI summaries."""
import hashlib
import json

from database.ai_queries import get_fingerprint_stats
from database.settings_queries import get_budgets, get_categories


def compute_data_fingerprint(user_id, prefs, prompt_version, model):
    """Hash the data that can change an AI summary, so stale caches are ignored."""
    categories = get_categories(user_id, type="expense", include_archived=True)
    budgets = get_budgets(user_id)
    payload = {
        "prompt_version": prompt_version,
        "model": model,
        "preferences": dict(prefs or {}),
        "categories": [
            {
                "id": category["id"],
                "name": category["name"],
                "is_archived": bool(category["is_archived"]),
            }
            for category in sorted(categories, key=lambda category: category["id"])
        ],
        "budgets": [
            {
                "id": budget["id"],
                "category_id": budget["category_id"],
                "monthly_limit": float(budget["monthly_limit"]),
            }
            for budget in sorted(
                budgets, key=lambda budget: (budget["category_id"] or -1, budget["id"])
            )
        ],
        "source": get_fingerprint_stats(user_id),
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
