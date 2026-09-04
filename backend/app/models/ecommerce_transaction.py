"""One row per purchase, so a purchase can only be counted once.

This is the idempotency guarantee that used to be a partial unique index on
ecommerce_events. That table is partitioned by time now, and a hypertable
requires the partitioning column in every unique index: including the
timestamp would have permitted the same transaction again at a different
time, which is precisely what the index existed to prevent.

So the claim lives here instead, in a table nothing needs to partition. The
tracking path inserts a row before writing the event, and a second attempt at
the same transaction hits the primary key and is refused.

Deliberately narrow. It holds no revenue, no currency, no product and no
visitor, because nothing reads it: it exists to be collided with. Retention
deletes from it on the same schedule as the events, so a claim never outlives
the purchase it protects.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, func

from app.database import Base


class EcommerceTransaction(Base):
    __tablename__ = "ecommerce_transactions"

    website_id = Column(
        Integer,
        ForeignKey("websites.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    event_type = Column(String(50), primary_key=True, nullable=False)
    transaction_id = Column(String(255), primary_key=True, nullable=False)

    #: When the claim was made. Retention deletes by this.
    first_seen = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_ecommerce_transactions_first_seen", "first_seen"),
    )

    def __repr__(self) -> str:
        return (
            f"<EcommerceTransaction(website_id={self.website_id}, "
            f"event_type={self.event_type!r}, transaction_id={self.transaction_id!r})>"
        )
