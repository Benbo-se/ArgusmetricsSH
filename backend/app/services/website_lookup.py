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


def resolve_tracking_code(db: Session, tracking_code: str) -> Optional[TrackedWebsite]:
    """The website a tracking code belongs to, or None.

    Returns inactive and unverified websites too. Callers decide what to do
    with them, because they report those two cases differently: an inactive
    site is an invalid code, an unverified one is a domain that has not proved
    ownership yet.
    """
    row = db.execute(
        text(
            "SELECT id, domain, is_verified, is_active "
            "FROM argus_resolve_tracking_code(:code)"
        ),
        {"code": tracking_code},
    ).first()

    if row is None:
        return None

    return TrackedWebsite(
        id=row.id,
        domain=row.domain,
        is_verified=row.is_verified,
        is_active=row.is_active,
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
