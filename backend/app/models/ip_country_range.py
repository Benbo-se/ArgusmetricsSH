"""Which address ranges belong to which country.

Built from the five Regional Internet Registries' own published allocation
files, which need no account and no licence, so a self-hosted instance can
have country statistics without depending on a vendor's download. See
app/services/ip_country_service.py for the loading and the caveats.

Nothing reads this through the ORM. The lookup runs as a SECURITY DEFINER
function because its caller is the tracking context, which deliberately has no
read access to anything, and the refresh writes in bulk. The class exists so
the table is part of the metadata Alembic compares against: without it,
autogenerate sees a table no model claims and proposes dropping it, and
`alembic check` fails on every future migration.
"""
from sqlalchemy import BigInteger, Column, DateTime, Index, String
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.sql import func

from app.database import Base


class IpCountryRange(Base):
    """One allocated range and the country it was allocated to.

    Attributes:
        start_ip: First address of the range, inclusive
        end_ip: Last address, inclusive. A range rather than a network because
            the registries publish IPv4 allocations as a count of addresses,
            which is not always a power of two and so is not always one CIDR
            block
        country: ISO 3166-1 alpha-2, as published. A few non-country codes
            appear (EU for "Europe, unspecified"), which is the registries'
            own data rather than something to correct
        registry: Which of the five published it, so a partial refresh is
            visible per region
        refreshed_at: When this row was loaded. The whole table is replaced at
            once, so these agree within a refresh
    """

    __tablename__ = "ip_country_ranges"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    start_ip = Column(INET, nullable=False)
    end_ip = Column(INET, nullable=False)
    country = Column(String(2), nullable=False)
    registry = Column(String(16), nullable=False)
    refreshed_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # The lookup is "the last range starting at or before this address", which
    # is an index scan backwards that stops at the first row.
    __table_args__ = (
        Index("ix_ip_country_ranges_start", "start_ip"),
    )

    def __repr__(self) -> str:
        return (
            f"<IpCountryRange {self.start_ip}-{self.end_ip} {self.country}>"
        )
