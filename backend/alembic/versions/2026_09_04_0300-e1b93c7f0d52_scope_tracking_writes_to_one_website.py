"""Scope the tracking write policies to one website

Closes a gap I left when the traffic-table policies first landed. The write
policies said only this:

    WITH CHECK (current_setting('app.context', true) = 'tracking')

Nothing about which website. So under those policies a tracking request could
insert a pageview, a custom event, a purchase or a conversion against any
customer's website. The application never does, because it resolves the
tracking code first, but a policy exists precisely for when the code above it
is wrong. A policy that says "any tenant" is not isolation.

The tracking context now carries the website it resolved (see
resolve_tracking_code, which narrows it at the one point where the website
becomes known), so these can require it.

funnel_events has no website_id of its own, so it reaches the website through
funnels. That table holds configuration rather than traffic, so the subquery
is cheap, and it gets its own policies in the next migration.

Note what this does to a request that never resolved a code: app.website_id is
empty, NULLIF gives NULL, the comparison is NULL rather than true, and the
insert is refused. Skipping the resolution step now fails closed.

Revision ID: e1b93c7f0d52
Revises: c5a70d1b8e46
Create Date: 2026-09-04 03:00:00.000000

"""
from alembic import op


revision = 'e1b93c7f0d52'
down_revision = 'c5a70d1b8e46'
branch_labels = None
depends_on = None


CTX = "current_setting('app.context', true)"
SITE = "NULLIF(current_setting('app.website_id', true), '')::int"

# How each table reaches the website it belongs to.
VIA = {
    "pageviews": "website_id",
    "custom_events": "website_id",
    "ecommerce_events": "website_id",
    "goal_conversions": "website_id",
    "funnel_events": "(SELECT f.website_id FROM funnels f WHERE f.id = funnel_id)",
}


def upgrade() -> None:
    for table, website_ref in VIA.items():
        op.execute(f"DROP POLICY {table}_tracking_write ON {table}")
        op.execute(
            f"""
            CREATE POLICY {table}_tracking_write ON {table}
            FOR INSERT
            WITH CHECK ({CTX} = 'tracking' AND {website_ref} = {SITE})
            """
        )


def downgrade() -> None:
    for table in VIA:
        op.execute(f"DROP POLICY {table}_tracking_write ON {table}")
        op.execute(
            f"""
            CREATE POLICY {table}_tracking_write ON {table}
            FOR INSERT
            WITH CHECK ({CTX} = 'tracking')
            """
        )
