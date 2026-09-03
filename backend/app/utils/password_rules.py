"""
Password rules — the single source of truth for password strength.

Both the server-side gate (signup / set-password) and the live checklist in
the auth templates consume these rule ids, so UI and enforcement cannot
drift apart. Rules follow the same trio a Django default setup enforces:
length, not-all-digits, not-similar-to-email, plus a common-password list.
"""
from typing import List, Tuple

MIN_LENGTH = 8

# Top common passwords (lowercased). Small on purpose: this catches the
# lazy defaults; a breach-corpus check (HIBP k-anonymity) can be added later.
_COMMON_PASSWORDS = {
    "password", "password1", "password123", "passw0rd", "12345678", "123456789",
    "1234567890", "qwerty123", "qwertyuiop", "iloveyou", "sunshine", "princess",
    "admin123", "welcome1", "welcome123", "letmein1", "football", "baseball",
    "superman", "trustno1", "dragon123", "master123", "monkey123", "shadow123",
    "abc12345", "abcd1234", "11111111", "00000000", "aa123456", "a1234567",
    "password!", "changeme", "changeme1", "secret123", "hej12345", "sommar2024",
    "sommar2025", "sommar2026",
}

# Rule ids are stable identifiers; templates map them to human labels.
RULES = ("length", "not_all_digits", "not_email", "not_common")


def password_checks(password: str, email: str = "") -> List[Tuple[str, bool]]:
    """Evaluate every rule; returns [(rule_id, passed), ...] in RULES order."""
    pw = password or ""
    local_part = (email or "").split("@")[0].lower()

    return [
        ("length", len(pw) >= MIN_LENGTH),
        ("not_all_digits", not pw.isdigit()),
        ("not_email", not (local_part and len(local_part) >= 4 and local_part in pw.lower())),
        ("not_common", pw.lower() not in _COMMON_PASSWORDS),
    ]


def password_ok(password: str, email: str = "") -> bool:
    """True when every rule passes."""
    return all(ok for _, ok in password_checks(password, email))


def failed_rules(password: str, email: str = "") -> List[str]:
    """Rule ids that did not pass (for error responses)."""
    return [rule for rule, ok in password_checks(password, email) if not ok]
