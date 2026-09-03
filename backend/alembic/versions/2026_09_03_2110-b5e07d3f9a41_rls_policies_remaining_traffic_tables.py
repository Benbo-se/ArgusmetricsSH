"""Extend row-level security to the remaining traffic tables

Follows the same shape proven on pageviews: custom_events, ecommerce_events,
goal_conversions and funnel_events. All four carry the denormalised
owner_email, so the common case stays an indexed equality.

funnel_events is the one that differs. It has no website_id of its own, so the
public-dashboard policy reaches its website through funnels. That table is
small and its rows are configuration rather than traffic, so the join is
cheap.

Rolled out only after the cross-tenant test existed, so each table here is
verified by it rather than by hand.

Revision ID: b5e07d3f9a41
Revises: 9c4d1f7a2b60
Create Date: 2026-09-03 21:10:00.000000

"""
from alembic import op


revision = 'b5e07d3f9a41'
down_revision = '9c4d1f7a2b60'
branch_labels = None
depends_on = None


# Tables with their own website_id column
VIA_WEBSITE = ["custom_events", "ecommerce_events", "goal_conversions"]
ALL_TABLES = VIA_WEBSITE + ["funnel_events"]


def upgrade() -> None:
    for table in ALL_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

        # Owned rows, plus anything shared through team membership.
        op.execute(
            f"""
            CREATE POLICY {table}_user_read ON {table}
            FOR SELECT
            USING (
                current_setting('app.context', true) = 'user'
                AND (
                    owner_email = current_setting('app.user_email', true)
                    OR {'website_id' if table in VIA_WEBSITE else
                        '(SELECT f.website_id FROM funnels f WHERE f.id = funnel_id)'} IN (
                        SELECT wm.website_id
                          FROM website_members wm
                         WHERE wm.user_email = current_setting('app.user_email', true)
                    )
                )
            )
            """
        )

        # A public share link is pinned to the single website it resolved to.
        website_ref = (
            "website_id" if table in VIA_WEBSITE
            else "(SELECT f.website_id FROM funnels f WHERE f.id = funnel_id)"
        )
        op.execute(
            f"""
            CREATE POLICY {table}_public_read ON {table}
            FOR SELECT
            USING (
                current_setting('app.context', true) = 'public'
                AND {website_ref} = NULLIF(current_setting('app.website_id', true), '')::int
            )
            """
        )

        # The tracking endpoints may record events and may not read them.
        op.execute(
            f"""
            CREATE POLICY {table}_tracking_write ON {table}
            FOR INSERT
            WITH CHECK (current_setting('app.context', true) = 'tracking')
            """
        )

        # Retention and scheduled reports span every tenant by nature.
        op.execute(
            f"""
            CREATE POLICY {table}_job_all ON {table}
            FOR ALL
            USING (current_setting('app.context', true) = 'job')
            WITH CHECK (current_setting('app.context', true) = 'job')
            """
        )


def downgrade() -> None:
    for table in ALL_TABLES:
        for suffix in ("job_all", "tracking_write", "public_read", "user_read"):
            op.execute(f"DROP POLICY IF EXISTS {table}_{suffix} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
