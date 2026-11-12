"""Besökardimensioner på pageviews: OS, versioner, språk, hostname (#204)

Fem nya kolumner på pageviews: os, os_version, browser_version, language och
hostname. Skärmbredden lagras redan.

pageviews är en hypertabell med riktiga data, så det som spelar roll är vad
ALTER TABLE gör med den:

  - Kolumnerna är nullable och har inget DEFAULT. Då skriver Postgres bara om
    katalogen, inga rader rörs, och TimescaleDB för ändringen vidare till varje
    chunk på samma sätt. Tiden beror på antalet chunkar, inte på antalet rader.
  - Komprimering är avstängd på alla hypertabeller och det finns inga
    kontinuerliga aggregat (radnivåsäkerheten utesluter båda, se a7c4e91b3d52
    och test_hypertables.py), så ingen av TimescaleDB:s begränsningar för
    ADD COLUMN gäller här.
  - ADD COLUMN tar ACCESS EXCLUSIVE på tabellen och dess chunkar. Låset hålls
    kort, men väntan på det kan bli lång bakom en långsam fråga, och under
    väntan köar varje INSERT bakom migreringen. lock_timeout gör att
    migreringen då hellre misslyckas än håller spårningen stilla. SET LOCAL
    gäller bara den här transaktionen.
  - Ingen backfyllnad. Äldre rader har NULL, vilket rapporterna visar som
    "Unknown". Värdena går inte att återskapa: user agent och Accept-Language
    har aldrig sparats.
  - Inga index. Tabellen är skrivtung och kolumnerna har låg kardinalitet;
    rapporterna avgränsas redan av website_id och tid.

Radnivåsäkerheten och rättigheterna ligger på tabellnivå och täcker nya
kolumner utan ändring.

Revision ID: e5f7b8d4c938
Revises: d7c3a15f9e28
Create Date: 2026-11-12 13:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


revision = 'e5f7b8d4c938'
down_revision = 'd7c3a15f9e28'
branch_labels = None
depends_on = None


COLUMNS = (
    ('os', 50),
    ('os_version', 20),
    ('browser_version', 20),
    ('language', 10),
    ('hostname', 253),
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for name, length in COLUMNS:
        op.add_column('pageviews', sa.Column(name, sa.String(length), nullable=True))


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    for name, _ in reversed(COLUMNS):
        op.drop_column('pageviews', name)
