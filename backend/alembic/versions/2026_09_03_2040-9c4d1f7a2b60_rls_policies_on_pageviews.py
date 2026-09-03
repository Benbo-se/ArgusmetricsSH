"""Enable row-level security on pageviews

Step 2 of the RLS rollout, deliberately one table at a time. A wrong policy
does not raise: it returns fewer rows, which surfaces as "no data" in the
dashboard rather than as an error. Doing pageviews alone means that if the
numbers move, there is only one thing it can be.

The policies read the context that every request now declares (see
app/database.py). current_setting(..., true) returns NULL when nothing was
set, and comparing NULL yields NULL rather than true, so a request that
declares nothing sees nothing. Forgetting to declare a context fails closed.

Access per context:
  user      rows they own, plus rows for websites they are a member of
  public    read-only, and only the single website whose share token resolved
  tracking  insert only, no read at all
  job       everything, for retention and scheduled reports

Note on FORCE ROW LEVEL SECURITY: deliberately not used. Policies do not apply
to a table's owner, and migrations run as the owner, so forcing it would make
future data migrations see an empty table. In production the application
connects as argus_app, which owns nothing, so the policies apply to it.

That has a consequence worth knowing: in development the app connects as the
owner, so these policies are inert there. Verify them by connecting as
argus_app explicitly, and make sure any cross-tenant test does the same, or it
will pass without proving anything.

Revision ID: 9c4d1f7a2b60
Revises: 7b2e9c14a3d8
Create Date: 2026-09-03 20:40:00.000000

"""
from alembic import op


revision = '9c4d1f7a2b60'
down_revision = '7b2e9c14a3d8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE pageviews ENABLE ROW LEVEL SECURITY")

    # An authenticated person sees what they own, plus anything shared with them
    # through team membership. owner_email is the denormalised column, so the
    # common case is an indexed equality rather than a join.
    op.execute(
        """
        CREATE POLICY pageviews_user_read ON pageviews
        FOR SELECT
        USING (
            current_setting('app.context', true) = 'user'
            AND (
                owner_email = current_setting('app.user_email', true)
                OR website_id IN (
                    SELECT wm.website_id
                      FROM website_members wm
                     WHERE wm.user_email = current_setting('app.user_email', true)
                )
            )
        )
        """
    )

    # A public dashboard is anonymous, so it is pinned to the one website whose
    # share token resolved, and can only read.
    op.execute(
        """
        CREATE POLICY pageviews_public_read ON pageviews
        FOR SELECT
        USING (
            current_setting('app.context', true) = 'public'
            AND website_id = NULLIF(current_setting('app.website_id', true), '')::int
        )
        """
    )

    # The tracking endpoints take input from any visitor's browser. They may
    # record a pageview and may not read one, so an injection there cannot be
    # turned into a data dump.
    op.execute(
        """
        CREATE POLICY pageviews_tracking_write ON pageviews
        FOR INSERT
        WITH CHECK (current_setting('app.context', true) = 'tracking')
        """
    )

    # Retention purges and scheduled reports span every tenant by nature.
    op.execute(
        """
        CREATE POLICY pageviews_job_all ON pageviews
        FOR ALL
        USING (current_setting('app.context', true) = 'job')
        WITH CHECK (current_setting('app.context', true) = 'job')
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS pageviews_job_all ON pageviews")
    op.execute("DROP POLICY IF EXISTS pageviews_tracking_write ON pageviews")
    op.execute("DROP POLICY IF EXISTS pageviews_public_read ON pageviews")
    op.execute("DROP POLICY IF EXISTS pageviews_user_read ON pageviews")
    op.execute("ALTER TABLE pageviews DISABLE ROW LEVEL SECURITY")
