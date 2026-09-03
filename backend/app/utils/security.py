"""
Security utilities for token generation and validation.

This module provides functions for:
- Generating magic link tokens for passwordless authentication
- Verifying magic link tokens with expiration
- Generating secure session tokens
- Email validation
"""
import re
import secrets
from typing import Optional
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

import logging

logger = logging.getLogger(__name__)


def generate_magic_token(email: str, secret: str, expires_in: int = 900, purpose: str = "verify") -> str:
    """
    Generate a time-limited magic link token for email verification.

    Creates a cryptographically signed token containing the user's email address.
    The token is URL-safe and expires after the specified time period.

    Args:
        email: User's email address to encode in the token
        secret: Secret key for signing the token (from app settings)
        expires_in: Token expiration time in seconds (default: 900 = 15 minutes)

    Returns:
        str: URL-safe signed token

    Example:
        token = generate_magic_token("user@example.com", settings.SECRET_KEY)
        # Returns: "InVzZXJAZXhhbXBsZS5jb20i.ZkF8Xw.1a2b3c4d5e6f..."
    """
    serializer = URLSafeTimedSerializer(secret)
    # Embed a random jti (for single-use enforcement) and the intended max age
    # so the token's lifetime is honored at verification time.
    payload = {
        "email": email,
        "jti": secrets.token_urlsafe(16),
        "max_age": int(expires_in),
        "purpose": purpose,
    }
    token = serializer.dumps(payload, salt="email-verification")

    logger.debug("Generated single-use magic token (expires in %ss)", expires_in)
    return token


def verify_magic_token(token: str, secret: str, max_age: int = 900, expected_purpose: str = "verify") -> dict:
    """
    Verify and decode a magic link token.

    Validates the token signature and checks it hasn't expired. Returns the
    decoded payload ``{"email": ..., "jti": ...}``. The ``jti`` is used by the
    caller to enforce single-use (reject replays).

    Args:
        token: The magic link token to verify
        secret: Secret key used to sign the token (from app settings)
        max_age: Fallback maximum age in seconds if the token carries none

    Returns:
        dict: ``{"email": str, "jti": Optional[str]}``

    Raises:
        SignatureExpired: If the token has expired
        BadSignature: If the token signature is invalid
    """
    serializer = URLSafeTimedSerializer(secret)

    try:
        # Load once without age enforcement to read the token's own max_age,
        # then re-validate against the smaller of the embedded/explicit ages.
        raw = serializer.loads(token, salt="email-verification")
        if isinstance(raw, dict):
            # A verify-token must not be usable as a reset-token or vice versa.
            # Tokens minted before purposes existed count as "verify".
            token_purpose = raw.get("purpose", "verify")
            if token_purpose != expected_purpose:
                logger.warning("Magic token purpose mismatch: %s != %s", token_purpose, expected_purpose)
                raise BadSignature("purpose mismatch")
            effective_age = min(int(raw.get("max_age", max_age)), max_age)
            # Re-load with the effective age so an expired token raises.
            serializer.loads(token, salt="email-verification", max_age=effective_age)
            return {"email": raw.get("email"), "jti": raw.get("jti")}
        # Backward-compat: legacy tokens were a bare email string.
        serializer.loads(token, salt="email-verification", max_age=max_age)
        return {"email": raw, "jti": None}
    except SignatureExpired:
        logger.warning("Magic token expired")
        raise
    except BadSignature:
        logger.warning("Invalid magic token signature")
        raise


def generate_session_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure random session token.

    Uses the secrets module to generate a URL-safe random token suitable
    for session management. The token is suitable for use in cookies or
    authorization headers.

    Args:
        length: Number of random bytes to generate (default: 32)
                The resulting token will be approximately length*1.3 characters

    Returns:
        str: URL-safe random token

    Example:
        token = generate_session_token()
        # Returns: "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6..."
    """
    token = secrets.token_urlsafe(length)
    logger.debug(f"Generated session token of length {len(token)}")
    return token


def validate_email(email: str) -> bool:
    """
    Validate email address format using regex pattern.

    Performs basic email validation to ensure the email address has a valid
    format. This is a simple validation and doesn't check if the email
    actually exists or is deliverable.

    Args:
        email: Email address to validate

    Returns:
        bool: True if email format is valid, False otherwise

    Example:
        validate_email("user@example.com")  # Returns: True
        validate_email("invalid.email")      # Returns: False
        validate_email("user@domain")        # Returns: False
    """
    # Basic email regex pattern
    # Matches: local-part@domain.tld
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'

    is_valid = bool(re.match(pattern, email))

    if not is_valid:
        logger.debug("Invalid email format provided")

    return is_valid


def hash_token(token: str) -> str:
    """
    Hash a token for secure storage.

    Note: For production use, consider using a proper password hashing
    library like bcrypt or argon2. This is a placeholder implementation.

    Args:
        token: Token to hash

    Returns:
        str: Hashed token

    Example:
        hashed = hash_token("my-secret-token")
    """
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


def generate_visitor_hash(ip_address: str, user_agent: str, website_domain: str) -> str:
    """
    Generate a GDPR-compliant privacy-safe visitor hash.

    Uses: daily_salt + SECRET_KEY + website_domain + truncated_IP + user_agent
    - Daily rotation: impossible to track across days
    - IP truncation (/24): impossible to identify individual in shared network
    - Domain scoping: hashes are site-specific, no cross-site correlation
    - SECRET_KEY: non-reversible even with algorithm knowledge
    """
    import hashlib
    from datetime import datetime, timezone
    from app.config import settings

    # IPv4: truncate last octet → /24 subnet (192.168.1.123 → 192.168.1.0)
    # IPv6: truncate to first 3 groups → /48 prefix
    parts = ip_address.split('.')
    if len(parts) == 4:
        truncated_ip = '.'.join(parts[:3]) + '.0'
    else:
        ipv6_parts = ip_address.split(':')
        truncated_ip = ':'.join(ipv6_parts[:3]) + '::'

    # Daily salt = YYYY-MM-DD + SECRET_KEY (UTC)
    daily_salt = datetime.now(timezone.utc).strftime('%Y-%m-%d') + settings.SECRET_KEY

    combined = f"{daily_salt}:{website_domain}:{truncated_ip}:{user_agent}"
    return hashlib.sha256(combined.encode('utf-8')).hexdigest()
