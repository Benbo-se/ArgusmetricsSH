"""Minne av senaste trafiklarm per webbplats

Larmjobbet körs varje timme och kom inte ihåg att det redan hade larmat, så en
trafiktopp som varade i flera timmar gav ett mejl per timme. Kolumnen låter
kontrollen vara tyst en stund efter ett larm.

Kolumnen är nullable och ingen backfyllnad behövs: NULL betyder att inget larm
har gått, vilket är sant för alla befintliga rader. alert_settings har redan
radnivåsäkerhet och rättigheter på tabellnivå, som täcker den nya kolumnen.

Revision ID: d9e4a6c3b827
Revises: c8d3f5b2a716
Create Date: 2026-11-12 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


revision = 'd9e4a6c3b827'
down_revision = 'c8d3f5b2a716'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'alert_settings',
        sa.Column('last_alerted_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('alert_settings', 'last_alerted_at')
