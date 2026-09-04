"""How much each account has recorded this month.

Kept as it happens rather than counted on demand, because the limit is checked
on every pageview and counting rows there would be O(everything the account
has ever recorded) on the hottest path in the product.

Maintained by a trigger, like owner_email, so no tracking path can forget to
increment it. Do not write to it from application code.
"""
from sqlalchemy import BigInteger, Column, Date, DateTime, String
from sqlalchemy.sql import func

from app.database import Base


class AccountUsage(Base):
    """One row per account per calendar month.

    Attributes:
        owner_email: The account, not the website. A pageview costs the same
            whichever domain it came from
        period_start: The first of the month
        events: Pageviews, custom events and ecommerce events together
    """

    __tablename__ = "account_usage"

    owner_email = Column(String(255), primary_key=True)
    period_start = Column(Date, primary_key=True)
    events = Column(BigInteger, nullable=False, server_default="0", default=0)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<AccountUsage(owner_email='{self.owner_email}', "
            f"period_start={self.period_start}, events={self.events})>"
        )
