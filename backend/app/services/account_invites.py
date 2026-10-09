"""Letting one named person create an account while signup is closed.

The operator names an address on the admin page, the link goes to that
address, and opening it lets the person choose a password. The account has no
websites; they add their own. Registration stays closed for everyone else.

The address is taken from the invitation, never from the person accepting it,
so a forwarded link creates the account it was sent for and no other. The
account is verified on creation: the link reached that inbox, which is what a
verification email would have asked.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import set_rls_context
from app.models.account_invitation import AccountInvitation
from app.models.session import Session as SessionModel
from app.models.user import User
from app.utils.password_rules import failed_rules, password_ok
from app.utils.security import mask_email

logger = logging.getLogger(__name__)

#: How long a link works. Long enough to survive a weekend in an inbox.
INVITE_DAYS = 14


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalise(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@") or " " in email:
        raise ValueError("That is not an email address.")
    return email


def create(db: Session, email: str, invited_by: str) -> str:
    """Invite an address and return the token for its link.

    Inviting an address again replaces its unused invitation, so the newest
    link is the only one that works.
    """
    email = _normalise(email)
    set_rls_context(db, context="job")
    if db.query(User.id).filter(User.email == email).first():
        raise ValueError(f"{email} already has an account.")

    db.query(AccountInvitation).filter(
        AccountInvitation.email == email,
        AccountInvitation.accepted_at.is_(None),
    ).delete(synchronize_session=False)

    token = secrets.token_urlsafe(32)
    db.add(AccountInvitation(
        email=email,
        token_hash=_hash(token),
        invited_by=invited_by,
        expires_at=datetime.now(timezone.utc) + timedelta(days=INVITE_DAYS),
    ))
    db.commit()
    logger.info(f"Account invitation created for {mask_email(email)}")
    return token


def pending(db: Session) -> List[AccountInvitation]:
    """Unused invitations, newest first, expired ones included so the
    operator can see that a link ran out."""
    set_rls_context(db, context="job")
    return (
        db.query(AccountInvitation)
        .filter(AccountInvitation.accepted_at.is_(None))
        .order_by(AccountInvitation.created_at.desc())
        .all()
    )


def revoke(db: Session, invitation_id: int) -> None:
    set_rls_context(db, context="job")
    db.query(AccountInvitation).filter(
        AccountInvitation.id == invitation_id,
        AccountInvitation.accepted_at.is_(None),
    ).delete(synchronize_session=False)
    db.commit()


def resolve(db: Session, token: str) -> Optional[str]:
    """The address a usable invitation is for, or None."""
    if not token:
        return None
    return db.execute(
        text("SELECT email FROM argus_resolve_account_invite(:h)"),
        {"h": _hash(token)},
    ).scalar()


def accept(db: Session, token: str, password: str) -> SessionModel:
    """Create the account the invitation is for, and sign it in.

    Raises ValueError, with a message safe to show, for every refusal.
    """
    from app.services.auth_service import AuthService, _hash_password

    email = resolve(db, token)
    if email is None:
        raise ValueError("This invitation is no longer valid.")
    if not password or not password_ok(password, email):
        raise ValueError(
            "Password does not meet the requirements: "
            + ", ".join(failed_rules(password or "", email))
        )
    if db.query(User.id).filter(User.email == email).first():
        raise ValueError("An account already exists for this address. Sign in instead.")

    # Used and created in one transaction: if creating the account fails,
    # the rollback leaves the link working.
    used = db.execute(
        text("SELECT argus_use_account_invite(:h)"), {"h": _hash(token)}
    ).scalar()
    if used is None:
        db.rollback()
        raise ValueError("This invitation is no longer valid.")

    user = User(email=email, is_verified=True, password_hash=_hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    logger.info(f"Account created from an account invitation: {mask_email(email)}")
    return AuthService(db).create_session(user)
