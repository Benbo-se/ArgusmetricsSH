"""Row-level security on api_tokens and alert_settings

Both hang off a website and are read only in the user and job contexts, so
neither needs anything the earlier migrations did not already build.

They do need a way to ask who owns a website. argus_member_role cannot answer
it: a website's owner does not necessarily have a website_members row, since
that row is backfilled the first time someone opens the team page. So
argus_website_owner joins websites, as SECURITY DEFINER for the same reason as
the rest, and the two helpers together express every rule below without a
subquery.

The policies mirror the routes, no wider:

  api_tokens      read    any active member, matching "any active member may
                          list tokens"
                  write   owner only, because a token authenticates as the
                          owner and so minting or revoking one is an
                          ownership decision
                  update  owner only, which covers last_used_at on the
                          API-token authentication path

  alert_settings  read    any active member
                  insert  any active member, because get_or_create_settings
                          creates a row on first read
                  update  owner or admin, matching "viewers must not change
                          settings"

The scheduled traffic-alert job reads alert_settings across every tenant, so
the job context keeps full access, as on every other table.

Revision ID: c5a70d1b8e46
Revises: d92f7b3e5a18
Create Date: 2026-09-04 02:30:00.000000

"""
from alembic import op


revision = 'c5a70d1b8e46'
down_revision = 'd92f7b3e5a18'
branch_labels = None
depends_on = None


ME = "current_setting('app.user_email', true)"
CTX = "current_setting('app.context', true)"
OWNER = "argus_website_owner(website_id) = " + ME
MEMBER = "argus_member_role(website_id, " + ME + ") IS NOT NULL"
ADMIN = "argus_member_role(website_id, " + ME + ") = 'admin'"


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_website_owner(site_id integer)
        RETURNS text
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT w.user_email FROM websites w WHERE w.id = site_id
        $$;
        """
    )

    for table in ("api_tokens", "alert_settings"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {table}_user_read ON {table}
            FOR SELECT
            USING ({CTX} = 'user' AND ({OWNER} OR {MEMBER}))
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

    # Minting or revoking a token is an ownership decision: it authenticates
    # as the owner and unlocks the website's data.
    for action in ("INSERT", "UPDATE", "DELETE"):
        clause = "WITH CHECK" if action == "INSERT" else "USING"
        extra = f" WITH CHECK ({CTX} = 'user' AND {OWNER})" if action == "UPDATE" else ""
        op.execute(
            f"""
            CREATE POLICY api_tokens_user_{action.lower()} ON api_tokens
            FOR {action}
            {clause} ({CTX} = 'user' AND {OWNER}){extra}
            """
        )

    # get_or_create_settings writes a row the first time anyone opens the
    # alerts page, so creating one is not a privileged action. Changing the
    # thresholds is.
    op.execute(
        f"""
        CREATE POLICY alert_settings_user_insert ON alert_settings
        FOR INSERT
        WITH CHECK ({CTX} = 'user' AND ({OWNER} OR {MEMBER}))
        """
    )
    op.execute(
        f"""
        CREATE POLICY alert_settings_user_update ON alert_settings
        FOR UPDATE
        USING ({CTX} = 'user' AND ({OWNER} OR {ADMIN}))
        WITH CHECK ({CTX} = 'user' AND ({OWNER} OR {ADMIN}))
        """
    )
    op.execute(
        f"""
        CREATE POLICY alert_settings_user_delete ON alert_settings
        FOR DELETE
        USING ({CTX} = 'user' AND {OWNER})
        """
    )


def downgrade() -> None:
    for suffix in ("user_delete", "user_update", "user_insert", "job_all", "user_read"):
        op.execute(f"DROP POLICY IF EXISTS alert_settings_{suffix} ON alert_settings")
        op.execute(f"DROP POLICY IF EXISTS api_tokens_{suffix} ON api_tokens")
    for table in ("api_tokens", "alert_settings"):
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS argus_website_owner(integer)")
