"""Tidszon per webbplats

Allt räknades i UTC, så en svensk sajts dygn började 01:00 eller 02:00.
Kolumnen håller ett IANA-namn och frågorna räknar dygn i den zonen.

Befintliga rader får UTC genom kolumnens standardvärde, så ingen sajt byter
dygnsgräns av att migrationen körs: det sker först när någon väljer en zon i
inställningarna. Ingen backfyllnad av mätdata behövs, eftersom inget lagras
per dygn. Tidsstämplarna ligger kvar i UTC och dygnet räknas ut vid läsning,
så ett byte av zon gäller även historiken och går att ångra.

Namnet valideras i applikationen (mot zoneinfo och mot pg_timezone_names),
inte med en CHECK: listan över zoner ändras med tzdata och hör inte hemma i
schemat. websites har redan radnivåsäkerhet och rättigheter på tabellnivå,
som täcker den nya kolumnen.

Revision ID: a6c2d8e4f913
Revises: e5f7b8d4c938
Create Date: 2026-11-12 14:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


revision = 'a6c2d8e4f913'
down_revision = 'e5f7b8d4c938'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'websites',
        sa.Column('timezone', sa.String(length=64), nullable=False, server_default='UTC'),
    )


def downgrade() -> None:
    op.drop_column('websites', 'timezone')
