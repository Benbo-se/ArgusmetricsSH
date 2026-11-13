"""TOTP (RFC 6238) on HOTP (RFC 4226), from the standard library.

Thirty lines of HMAC, written here rather than taken from a package because
the algorithm is fixed, small, and comes with published test vectors that
tests/test_totp.py checks it against. A dependency would be one more thing to
keep patched in the path that guards the login.

The parameters are the ones every authenticator app assumes and several
silently ignore being told otherwise: SHA-1, six digits, thirty seconds.
SHA-1 here is HMAC-SHA-1, which the collision attacks on SHA-1 do not touch.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Optional
from urllib.parse import quote

DIGITS = 6
PERIOD = 30

#: How many steps either side of now a code is accepted for. One step is the
#: usual allowance for a phone whose clock is half a minute off, and for a
#: code typed just as it rolled over.
WINDOW = 1


def generate_secret() -> str:
    """A new shared secret: 160 bits, base32, as RFC 4226 recommends."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _key(secret: str) -> bytes:
    cleaned = secret.replace(" ", "").upper()
    return base64.b32decode(cleaned + "=" * (-len(cleaned) % 8))


def hotp(key: bytes, counter: int, digits: int = DIGITS) -> str:
    """RFC 4226: the code for one counter value."""
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % (10 ** digits)).zfill(digits)


def step_at(timestamp: Optional[float] = None) -> int:
    """The time step a moment falls in."""
    return int((time.time() if timestamp is None else timestamp) // PERIOD)


def code_at(secret: str, step: int) -> str:
    """The code an authenticator shows during one time step."""
    return hotp(_key(secret), step)


def matching_step(
    secret: str,
    code: str,
    *,
    after_step: Optional[int] = None,
    timestamp: Optional[float] = None,
) -> Optional[int]:
    """The time step this code is valid for right now, or None.

    `after_step` is what stops a replay: only steps later than it count, so
    passing the step of the last accepted code means neither that code nor
    an older one is accepted again. The caller stores the returned step.

    Every candidate is compared, and in constant time, so how long this takes
    says nothing about which step matched or how close a guess was.
    """
    code = (code or "").strip()
    if len(code) != DIGITS or not code.isascii() or not code.isdigit():
        return None
    try:
        key = _key(secret)
    except (ValueError, TypeError):
        return None

    now = step_at(timestamp)
    matched = None
    for step in range(now - WINDOW, now + WINDOW + 1):
        same = hmac.compare_digest(hotp(key, step), code)
        if same and (after_step is None or step > after_step) and matched is None:
            matched = step
    return matched


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    """The otpauth:// URI an authenticator app reads from a QR code."""
    label = quote(f"{issuer}:{account}", safe="")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer, safe='')}"
        f"&algorithm=SHA1&digits={DIGITS}&period={PERIOD}"
    )
