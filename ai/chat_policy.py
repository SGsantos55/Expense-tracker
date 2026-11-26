"""Deterministic scope and intent rules for the chat assistant."""
REFUSAL = "I can only help with your recorded expenses, income, budgets and spending trends."

PROMPT_INJECTION_PATTERNS = (
    "ignore previous",
    "ignore all",
    "system prompt",
    "developer message",
    "reveal",
    "api key",
    "secret key",
    "tool schema",
    "internal instructions",
    "act as",
    "you are now",
    "pretend",
    "roleplay",
    "jailbreak",
    "bypass",
    "disregard",
)

INTENT_KEYWORDS = {
    "overview": ("overview", "summary", "how am i doing", "financial picture", "money"),
    "income": ("income", "salary", "earned", "earnings", "paycheck"),
    "comparison": ("compare", "compared", "previous", "change", "trend", "last month"),
    "expenses": ("expense", "spent", "spending", "cost", "purchase", "transaction"),
    "budget": ("budget", "remaining", "allowance", "limit", "over budget"),
    "category": ("category", "categories", "breakdown", "top category"),
    "search": ("find", "search", "show expenses", "show transactions", "which expenses"),
    "insights": ("insight", "why", "recommend", "suggest", "what should"),
    "what_if": ("what if", "if i", "reduce", "cut", "lower"),
}

FOLLOW_UPS = {
    "overview": ["How did my spending compare with last month?", "Which categories used the most budget?"],
    "income": ["How does income compare with last month?", "What is my savings after expenses?"],
    "expenses": ["Which category did I spend the most on?", "Show my largest recent expenses."],
    "budget": ["Which category is closest to its limit?", "How did spending compare with last month?"],
    "category": ["Show expenses in my largest category.", "How did that category compare with last month?"],
    "comparison": ["Which category increased the most?", "How is my budget looking this period?"],
    "search": ["Show expenses above a specific amount.", "Which category had the most transactions?"],
    "insights": ["Which budget is closest to its limit?", "How did my income change?"],
    "what_if": ["Which category has the most spend to reduce?", "Show my current category breakdown."],
}


def _normalise(message):
    return " ".join(str(message or "").lower().split())


def classify_intent(message, categories=None):
    text = _normalise(message)
    if not text:
        return None
    if any(pattern in text for pattern in PROMPT_INJECTION_PATTERNS):
        return None
    for category in categories or []:
        name = _normalise(category.get("name") if isinstance(category, dict) else category)
        if name and len(name) > 2 and name in text:
            return "category"
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return intent
    return None


def follow_up_suggestions(intent):
    return list(FOLLOW_UPS.get(intent, []))[:3]
