"""Encrypting the few values that have to be read back.

Almost every secret this application stores is stored as a hash: session
tokens, API tokens, invitation links, verification codes. That works because
the application only ever has to recognise them. A TOTP secret is different.
The server has to compute the current code from it, so it must be able to
read it, and a hash cannot be read.

So it is encrypted, with a key derived from SECRET_KEY. That is the one
secret every instance already has, and docker/.env on a server holds exactly
the variables it needs: a new required one would stop the next deploy.

What this buys, stated plainly. A copy of the database alone, a backup for
instance, does not contain working TOTP secrets. Someone who has both the
database and SECRET_KEY has them, as they have everything else SECRET_KEY
signs. It is protection for the dump, not against a compromised server.

**Rotating SECRET_KEY makes every sealed value unreadable.** For two-factor
authentication that means authenticator codes stop being accepted. Recovery
codes are stored as plain SHA-256 for exactly this reason and keep working,
and `./argus admin disable-2fa` turns it off from the server. Whoever rotates
the key should expect to set two-factor authentication up again afterwards.

The key is derived with HKDF rather than used directly: SECRET_KEY also signs
magic links and peppers hashes, and one key should not do two jobs. The label
names the purpose and a version, so a second use gets a different key and a
change of scheme can be told apart from the old one.
"""
import base64
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings

logger = logging.getLogger(__name__)


def _fernet(purpose: str) -> Fernet:
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f"argusmetrics/{purpose}/v1".encode("utf-8"),
    ).derive(settings.SECRET_KEY.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def seal(value: str, purpose: str) -> str:
    """Encrypt a value for storage. Authenticated, so tampering is detected."""
    return _fernet(purpose).encrypt(value.encode("utf-8")).decode("ascii")


def unseal(sealed: Optional[str], purpose: str) -> Optional[str]:
    """Read a sealed value back, or None when it cannot be read.

    None rather than an exception because the caller's answer is the same
    either way: there is no secret to check a code against. The usual cause
    is a SECRET_KEY that changed since the value was sealed.
    """
    if not sealed:
        return None
    try:
        return _fernet(purpose).decrypt(sealed.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError):
        # Nothing about the value or its label goes in the log line.
        logger.error(
            "A sealed value could not be read. SECRET_KEY has probably "
            "changed since it was stored."
        )
        return None
