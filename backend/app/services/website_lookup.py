"""Resolving a tracking code without reading the websites table.

The tracking endpoints are unauthenticated and take a tracking_code straight
from a visitor's browser. Under row-level security they get the narrowest
context there is, which does not include reading websites: a policy cannot see
a query's WHERE clause, so permitting one lookup by code would permit reading
every row, and a websites row carries verification tokens, a share token and a
password hash.

These helpers go through SECURITY DEFINER functions instead, which return only
the four fields the tracking path needs. See the migration
e7b204c8d915 for the reasoning in full.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrackedWebsite:
    """The only parts of a website the tracking path is allowed to see."""

    id: int
    domain: str
    is_verified: bool
    is_active: bool
    #: Whose account this is, for the monthly limit. Not shown to anyone.
    owner_email: str


def _scope_tracking_context(db: Session, website_id: int) -> None:
    """Pin the tracking context to one website, once that website is known.

    Only ever narrows, and only a tracking context. A request that declared
    something else, or nothing, is left alone: this function grants no access
    that was not already there, it takes access away.

    Imported here rather than at module scope to keep the import one-way,
    since database.py has no business knowing about this module.
    """
    from app.database import RLS_INFO_KEY, set_rls_context

    declared = db.info.get(RLS_INFO_KEY) or {}
    if declared.get("context") != "tracking":
        return

    set_rls_context(db, context="tracking", website_id=website_id)


def resolve_tracking_code(db: Session, tracking_code: str) -> Optional[TrackedWebsite]:
    """The website a tracking code belongs to, or None.

    Returns inactive and unverified websites too. Callers decide what to do
    with them, because they report those two cases differently: an inactive
    site is an invalid code, an unverified one is a domain that has not proved
    ownership yet.

    Narrows the tracking context to this website on the way out. This is the
    one point where the tracking path learns which website it is dealing with,
    so it is the only place that can, and putting it here means no tracking
    path can forget. Forgetting would deny access rather than grant it, which
    is the right way round for a mistake to fail.
    """
    row = db.execute(
        text(
            "SELECT id, domain, is_verified, is_active, owner_email "
            "FROM argus_resolve_tracking_code(:code)"
        ),
        {"code": tracking_code},
    ).first()

    if row is None:
        return None

    _scope_tracking_context(db, row.id)

    return TrackedWebsite(
        id=row.id,
        domain=row.domain,
        is_verified=row.is_verified,
        is_active=row.is_active,
        owner_email=row.owner_email,
    )


@dataclass(frozen=True)
class PublicWebsite:
    """The parts of a website an anonymous share-link viewer may see.

    Notably absent: user_email, tracking_code, verification_token and the
    email report settings.
    """

    id: int
    name: str
    domain: str
    is_public: bool
    public_password_enabled: bool
    public_password_hash: Optional[str]


def resolve_share_token(db: Session, share_token: str) -> Optional[PublicWebsite]:
    """The website a public share token points at, or None.

    Only returns websites that are actually shared: the function filters on
    is_public, so a link that was revoked resolves to nothing.
    """
    row = db.execute(
        text(
            "SELECT id, name, domain, is_public, public_password_enabled,"
            "       public_password_hash "
            "FROM argus_resolve_share_token(:token)"
        ),
        {"token": share_token},
    ).first()

    if row is None:
        return None

    return PublicWebsite(
        id=row.id,
        name=row.name,
        domain=row.domain,
        is_public=row.is_public,
        public_password_enabled=row.public_password_enabled,
        public_password_hash=row.public_password_hash,
    )


@dataclass(frozen=True)
class ApiTokenOwner:
    """Who an API token belongs to, and which website it is scoped to."""

    website_id: int
    owner_email: str


def resolve_api_token(db: Session, token_hash: str) -> Optional[ApiTokenOwner]:
    """The website and owner behind an API token, or None.

    Runs before any context is declared, which is the whole point: this is how
    an API-token request learns who it is acting as, so it cannot depend on
    already knowing.
    """
    row = db.execute(
        text(
            "SELECT website_id, owner_email FROM argus_resolve_api_token(:hash)"
        ),
        {"hash": token_hash},
    ).first()

    if row is None:
        return None

    return ApiTokenOwner(website_id=row.website_id, owner_email=row.owner_email)


@dataclass(frozen=True)
class PendingInvite:
    """What an invitation page shows, for someone who is not logged in."""

    website_name: str
    website_domain: str
    role: str
    invited_by: Optional[str]
    invited_at: object
    invitee_email: str


def resolve_invite_token(db: Session, invite_token: str) -> Optional[PendingInvite]:
    """A pending invitation, or None.

    Whoever opens an invitation link is not authenticated and may not have an
    account at all, so there is no user to declare a context for. The token is
    the credential, as a tracking code or a share token is.

    Only pending invitations resolve. An accepted or revoked one comes back as
    None, so a used link cannot be replayed.
    """
    row = db.execute(
        text(
            "SELECT website_name, website_domain, role, invited_by,"
            "       invited_at, invitee_email "
            "FROM argus_resolve_invite_token(:token)"
        ),
        {"token": invite_token},
    ).first()

    if row is None:
        return None

    return PendingInvite(
        website_name=row.website_name,
        website_domain=row.website_domain,
        role=row.role,
        invited_by=row.invited_by,
        invited_at=row.invited_at,
        invitee_email=row.invitee_email,
    )


def tracking_code_exists(db: Session, tracking_code: str) -> bool:
    """Whether any website already uses this code.

    Has to see every website, not just the caller's. A collision check that
    only looks at your own sites reports someone else's code as free, and the
    insert then fails on the unique constraint.
    """
    return bool(
        db.execute(
            text("SELECT argus_tracking_code_exists(:code)"),
            {"code": tracking_code},
        ).scalar()
    )
