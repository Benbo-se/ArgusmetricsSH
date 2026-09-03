"""Row-level security: only an active membership grants access

The user_read policies accepted any row in website_members. The application
requires status ACTIVE everywhere it resolves a role, so the policies were
more permissive than the code above them.

Two cases that made this wrong rather than merely untidy:

  pending   an invitation that was sent and never accepted
  revoked   access that was deliberately taken away

The second is the one that matters. Someone removed from a team kept database
level read access to that website's traffic. The application still refused
them at the route, so this was not exploitable on its own, but a policy exists
precisely for when the check above it is missing or wrong. A backstop that
trusts the thing it is backing up is not a backstop.

Caught by extending the cross-tenant test to cover membership status. It
failed on both pending and revoked before this migration.

Revision ID: c1f83a6d4e27
Revises: b5e07d3f9a41
Create Date: 2026-09-03 22:30:00.000000

"""
from alembic import op


revision = 'c1f83a6d4e27'
down_revision = 'b5e07d3f9a41'
branch_labels = None
depends_on = None


# The five traffic tables, with how each one reaches its website.
TABLES = {
    "pageviews": "website_id",
    "custom_events": "website_id",
    "ecommerce_events": "website_id",
    "goal_conversions": "website_id",
    "funnel_events": "(SELECT f.website_id FROM funnels f WHERE f.id = funnel_id)",
}


def _user_read_policy(table: str, website_ref: str, active_only: bool) -> str:
    status_clause = (
        "\n                       AND wm.status = 'active'::memberstatus"
        if active_only else ""
    )
    return f"""
        CREATE POLICY {table}_user_read ON {table}
        FOR SELECT
        USING (
            current_setting('app.context', true) = 'user'
            AND (
                owner_email = current_setting('app.user_email', true)
                OR {website_ref} IN (
                    SELECT wm.website_id
                      FROM website_members wm
                     WHERE wm.user_email = current_setting('app.user_email', true){status_clause}
                )
            )
        )
    """


def upgrade() -> None:
    for table, website_ref in TABLES.items():
        op.execute(f"DROP POLICY {table}_user_read ON {table}")
        op.execute(_user_read_policy(table, website_ref, active_only=True))


def downgrade() -> None:
    for table, website_ref in TABLES.items():
        op.execute(f"DROP POLICY {table}_user_read ON {table}")
        op.execute(_user_read_policy(table, website_ref, active_only=False))
