"""People waiting for hosted signup to open.

Registration is closed on argusmetrics.io while the hosted side is being
built. The signup page asks for an address rather than showing a form that
cannot be submitted, and this is where the address goes.

The columns are the whole point: an address, when it arrived, and which page
it came from. Nothing else. A product that argues it keeps no visitor log
should not grow one in the corner where nobody looks.
"""
from sqlalchemy import Column, DateTime, Index, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class WaitlistEntry(Base):
    """One address, once.

    Attributes:
        email: Lower-cased and unique, so joining twice is not two rows and
            the page can answer the same way either time
        source: Which page the person came from, to tell a CTA that works
            from one that nobody clicks. Not an identifier
        created_at: When they joined
        notified_at: Set when they have been told signup opened, so a second
            announcement does not reach the same person twice
    """

    __tablename__ = "waitlist"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), nullable=False, unique=True)
    source = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=func.now())
    notified_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_waitlist_created_at", "created_at"),)

    def __repr__(self) -> str:
        return f"<WaitlistEntry {self.id}>"
