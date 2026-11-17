"""Which address ranges belong to a hosting provider (#103).

Only the ranges announced by the networks listed in app/hosting_asns.py, taken
from IPtoASN's public file: some tens of thousands of rows, not the seven
hundred thousand the file holds. See
app/services/hosting_networks_service.py for the loading and the caveats.

Nothing reads this through the ORM. The lookup runs as a SECURITY DEFINER
function because its caller is the tracking context, which deliberately has no
read access to anything, and the refresh writes in bulk. The class exists so
the table is part of the metadata Alembic compares against: without it,
autogenerate sees a table no model claims and proposes dropping it, and
`alembic check` fails on every future migration.
"""
from sqlalchemy import BigInteger, Column, DateTime, Index
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.sql import func

from app.database import Base


class HostingNetworkRange(Base):
    """One range of addresses that a listed hosting provider announces.

    Attributes:
        start_ip: First address of the range, inclusive
        end_ip: Last address, inclusive
        refreshed_at: When this row was loaded. The whole table is replaced at
            once, so these agree within a refresh

    Neither the AS number nor the provider is kept. Neighbouring ranges are
    merged on the way in, whoever they belong to, and the only question the
    table has to answer is yes or no.
    """

    __tablename__ = "hosting_network_ranges"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    start_ip = Column(INET, nullable=False)
    end_ip = Column(INET, nullable=False)
    refreshed_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # The lookup is "the last range starting at or before this address", one
    # step backwards in this index, and then a comparison with that row's end.
    __table_args__ = (
        Index("ix_hosting_network_ranges_start", "start_ip"),
    )

    def __repr__(self) -> str:
        return f"<HostingNetworkRange {self.start_ip}-{self.end_ip}>"
