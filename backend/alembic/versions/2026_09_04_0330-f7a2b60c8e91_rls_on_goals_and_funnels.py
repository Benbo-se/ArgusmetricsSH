"""Row-level security on goals and funnels, the last two tables

These are the two the tracking path has to read. When a visitor triggers an
event the server asks "is there a goal matching this name" and "is this path a
step in a funnel", and without those lookups no conversion and no funnel step
is ever recorded.

That is why they came last. A policy cannot see a query's WHERE clause, so for
every other table the choice was between letting the tracking context read
everything or letting it read nothing, and the answer was a SECURITY DEFINER
function. Here there is a better answer, because the tracking context now
carries the website it resolved (see e1b93c7f0d52). The rule is simply that
tracking reads the configuration of the one website it is tracking, which is
both narrower than a function would have been and cheaper.

Reading stays read-only for tracking. Goals and funnels are created by people,
never by the tracking script.

The user rules mirror the routes:

  read    owner, or any active member
  write   owner, or an active admin, matching "You need admin or owner access
          to create funnels" and the same on goals

Revision ID: f7a2b60c8e91
Revises: e1b93c7f0d52
Create Date: 2026-09-04 03:30:00.000000

"""
from alembic import op


revision = 'f7a2b60c8e91'
down_revision = 'e1b93c7f0d52'
branch_labels = None
depends_on = None


ME = "current_setting('app.user_email', true)"
CTX = "current_setting('app.context', true)"
SITE = "NULLIF(current_setting('app.website_id', true), '')::int"
OWNER = "argus_website_owner(website_id) = " + ME
MEMBER = "argus_member_role(website_id, " + ME + ") IS NOT NULL"
ADMIN = "argus_member_role(website_id, " + ME + ") = 'admin'"

TABLES = ("goals", "funnels")


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

        op.execute(
            f"""
            CREATE POLICY {table}_user_read ON {table}
            FOR SELECT
            USING ({CTX} = 'user' AND ({OWNER} OR {MEMBER}))
            """
        )

        # The tracking script needs this configuration to know what counts as
        # a conversion, and only for the website it just resolved.
        op.execute(
            f"""
            CREATE POLICY {table}_tracking_read ON {table}
            FOR SELECT
            USING ({CTX} = 'tracking' AND website_id = {SITE})
            """
        )

        # A public dashboard renders funnel and goal charts, so it reads the
        # configuration behind them, pinned to its one website.
        op.execute(
            f"""
            CREATE POLICY {table}_public_read ON {table}
            FOR SELECT
            USING ({CTX} = 'public' AND website_id = {SITE})
            """
        )

        op.execute(
            f"""
            CREATE POLICY {table}_user_insert ON {table}
            FOR INSERT
            WITH CHECK ({CTX} = 'user' AND ({OWNER} OR {ADMIN}))
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_user_update ON {table}
            FOR UPDATE
            USING ({CTX} = 'user' AND ({OWNER} OR {ADMIN}))
            WITH CHECK ({CTX} = 'user' AND ({OWNER} OR {ADMIN}))
            """
        )
        op.execute(
            f"""
            CREATE POLICY {table}_user_delete ON {table}
            FOR DELETE
            USING ({CTX} = 'user' AND ({OWNER} OR {ADMIN}))
            """
        )

        op.execute(
            f"""
            CREATE POLICY {table}_job_all ON {table}
            FOR ALL
            USING ({CTX} = 'job')
            WITH CHECK ({CTX} = 'job')
            """
        )


def downgrade() -> None:
    for table in TABLES:
        for suffix in (
            "job_all", "user_delete", "user_update", "user_insert",
            "public_read", "tracking_read", "user_read",
        ):
            op.execute(f"DROP POLICY IF EXISTS {table}_{suffix} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
