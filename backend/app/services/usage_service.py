"""How much an account has used this month, and whether it may record more.

The limit is checked on every pageview, so this reads a counter maintained by
a database trigger rather than counting rows. See the account_usage migration.

Per account rather than per website: a pageview costs the same whichever
domain it came from.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings

logger = logging.getLogger(__name__)

#: The one refusal message the recording paths return when an account is over
#: its monthly limit. A constant rather than a literal in four files, because
#: the routers map exactly this to 429 and a typo would silently make it a 400.
LIMIT_MESSAGE = "Monthly limit reached for this account"


@dataclass(frozen=True)
class Usage:
    """This month's usage for one account."""

    events: int
    limit: int
    #: None when there is no limit, otherwise 0.0 to over 1.0
    fraction: Optional[float]

    @property
    def limited(self) -> bool:
        return self.limit > 0

    @property
    def exceeded(self) -> bool:
        return self.limited and self.events >= self.limit

    @property
    def nearly_exceeded(self) -> bool:
        """Worth warning about. Telling someone after the fact is no use."""
        return self.limited and not self.exceeded and (self.fraction or 0) >= 0.8

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.events) if self.limited else 0


def get_usage(db: Session, owner_email: str) -> Usage:
    """This calendar month's usage. A single primary-key lookup."""
    limit = settings.MONTHLY_EVENT_LIMIT

    events = db.execute(
        text(
            "SELECT events FROM account_usage "
            " WHERE owner_email = :e AND period_start = date_trunc('month', now())::date"
        ),
        {"e": owner_email},
    ).scalar() or 0

    return Usage(
        events=events,
        limit=limit,
        fraction=(events / limit) if limit > 0 else None,
    )


def may_record(db: Session, owner_email: str) -> bool:
    """Whether this account may record another event.

    Fails open. If the counter cannot be read we record the event: refusing a
    customer's traffic because a usage lookup failed loses data that cannot be
    recovered, while letting a few extra events through costs a row. The two
    mistakes are not the same size.
    """
    if settings.MONTHLY_EVENT_LIMIT <= 0:
        return True

    try:
        usage = get_usage(db, owner_email)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Usage lookup failed, recording anyway: {exc}")
        return True

    if usage.exceeded:
        logger.info(
            "Monthly limit reached, not recording",
            extra={"events": usage.events, "limit": usage.limit},
        )
        return False
    return True
