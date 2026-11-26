"""Per-user AI rate limits backed by ai_usage."""
import ai.config as config
from database.ai_queries import count_recent_usage


class RateLimitError(RuntimeError):
    """Raised when a user exceeds a configured AI quota."""


def check_summary_limit(user_id):
    if count_recent_usage(user_id, "summary", minutes=60) >= config.AI_SUMMARY_LIMIT_PER_HOUR:
        raise RateLimitError("Summary limit reached for this hour.")


def check_chat_limits(user_id):
    minute_count = count_recent_usage(user_id, "chat", minutes=1)
    day_count = count_recent_usage(user_id, "chat", minutes=1440)
    if minute_count >= config.AI_CHAT_LIMIT_PER_MINUTE:
        raise RateLimitError("Chat limit reached for this minute.")
    if day_count >= config.AI_CHAT_LIMIT_PER_DAY:
        raise RateLimitError("Chat limit reached for today.")
