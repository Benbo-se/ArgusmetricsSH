"""Row-level security on websites and website_members

The last two tables, and the two that behave least like the rest. A traffic
table is written by one context and read by one other. These are read in every
context, and written by users rather than by the tracking script, so they need
policies for INSERT, UPDATE and DELETE as well. Enabling RLS with only a SELECT
policy would deny every write.

Three problems had to be solved before this migration could exist. Each was
reproduced first rather than assumed.

**The tracking context.** It resolves a tracking code to a website, and a
policy cannot see a query's WHERE clause, so permitting that lookup permits
reading every row, tokens and password hash included. Solved in e7b204c8d915
and f3c6a81b7e40: the tracking and public paths go through SECURITY DEFINER
functions and get no policy here at all.

**Mutual reference.** A website is visible to its members and a membership is
visible to the website's owner, which had the two tables' policies referencing
each other:

    SELECT count(*) FROM websites
      -> infinite recursion detected in policy for relation "websites"

Solved in d4a91c05f6b2 by carrying owner_email on the membership row.

**Self reference.** Any active member may list the whole team, so
website_members' own policy needs to know whether the caller is a member,
which means reading website_members from inside its policy. That recurses the
same way. argus_member_role below is SECURITY DEFINER, so the lookup runs as
the owner, outside RLS, and the cycle cannot form.

The policies mirror what the application permits, no wider:

  websites        read     owner, or any active member
                  insert   only a website you own
                  update   owner, or an active admin
                  delete   owner only
  website_members read     your own row, the owner, or any active member
                  write    owner or admin, plus your own row so an invitation
                           can be accepted

Revision ID: b6e419af7c23
Revises: a8d5e2f1c904
Create Date: 2026-09-04 01:00:00.000000

"""
from alembic import op


revision = 'b6e419af7c23'
down_revision = 'a8d5e2f1c904'
branch_labels = None
depends_on = None


ME = "current_setting('app.user_email', true)"
CTX = "current_setting('app.context', true)"


def upgrade() -> None:
    # Reads website_members from inside a policy on website_members, which is
    # only possible because SECURITY DEFINER puts it outside RLS. STABLE so it
    # is evaluated once per statement rather than once per row.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_member_role(site_id integer, email text)
        RETURNS text
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT wm.role::text
              FROM website_members wm
             WHERE wm.website_id = site_id
               AND wm.user_email = email
               AND wm.status = 'active'::memberstatus
             LIMIT 1
        $$;
        """
    )

    op.execute("ALTER TABLE websites ENABLE ROW LEVEL SECURITY")

    op.execute(
        f"""
        CREATE POLICY websites_user_read ON websites
        FOR SELECT
        USING (
            {CTX} = 'user'
            AND (user_email = {ME} OR argus_member_role(id, {ME}) IS NOT NULL)
        )
        """
    )

    # A share link is anonymous and pinned to the one website it resolved to.
    op.execute(
        f"""
        CREATE POLICY websites_public_read ON websites
        FOR SELECT
        USING (
            {CTX} = 'public'
            AND id = NULLIF(current_setting('app.website_id', true), '')::int
        )
        """
    )

    # You may create a website for yourself and nobody else.
    op.execute(
        f"""
        CREATE POLICY websites_user_insert ON websites
        FOR INSERT
        WITH CHECK ({CTX} = 'user' AND user_email = {ME})
        """
    )

    # Admins configure settings, which is what the routes allow. The WITH CHECK
    # repeats the USING clause so an update cannot hand the website to someone
    # else on the way out.
    op.execute(
        f"""
        CREATE POLICY websites_user_update ON websites
        FOR UPDATE
        USING (
            {CTX} = 'user'
            AND (user_email = {ME} OR argus_member_role(id, {ME}) = 'admin')
        )
        WITH CHECK (
            {CTX} = 'user'
            AND (user_email = {ME} OR argus_member_role(id, {ME}) = 'admin')
        )
        """
    )

    # Deleting a website takes its traffic with it, so owners only.
    op.execute(
        f"""
        CREATE POLICY websites_user_delete ON websites
        FOR DELETE
        USING ({CTX} = 'user' AND user_email = {ME})
        """
    )

    op.execute(
        f"""
        CREATE POLICY websites_job_all ON websites
        FOR ALL
        USING ({CTX} = 'job')
        WITH CHECK ({CTX} = 'job')
        """
    )

    op.execute("ALTER TABLE website_members ENABLE ROW LEVEL SECURITY")

    # Any active member may list the team, which is what get_team_members
    # allows. owner_email covers the owner without naming websites.
    op.execute(
        f"""
        CREATE POLICY website_members_user_read ON website_members
        FOR SELECT
        USING (
            {CTX} = 'user'
            AND (
                user_email = {ME}
                OR owner_email = {ME}
                OR argus_member_role(website_id, {ME}) IS NOT NULL
            )
        )
        """
    )

    # Inviting is an admin action. The owner is covered separately because a
    # website's first membership row is created before any exists to check.
    op.execute(
        f"""
        CREATE POLICY website_members_user_insert ON website_members
        FOR INSERT
        WITH CHECK (
            {CTX} = 'user'
            AND (
                owner_email = {ME}
                OR argus_member_role(website_id, {ME}) IN ('owner', 'admin')
            )
        )
        """
    )

    # Admins revoke and change roles. Your own row is included so that
    # accepting an invitation works: at that moment you are still pending, so
    # no role check would pass.
    op.execute(
        f"""
        CREATE POLICY website_members_user_update ON website_members
        FOR UPDATE
        USING (
            {CTX} = 'user'
            AND (
                user_email = {ME}
                OR owner_email = {ME}
                OR argus_member_role(website_id, {ME}) IN ('owner', 'admin')
            )
        )
        WITH CHECK (
            {CTX} = 'user'
            AND (
                user_email = {ME}
                OR owner_email = {ME}
                OR argus_member_role(website_id, {ME}) IN ('owner', 'admin')
            )
        )
        """
    )

    op.execute(
        f"""
        CREATE POLICY website_members_user_delete ON website_members
        FOR DELETE
        USING (
            {CTX} = 'user'
            AND (
                owner_email = {ME}
                OR argus_member_role(website_id, {ME}) IN ('owner', 'admin')
            )
        )
        """
    )

    op.execute(
        f"""
        CREATE POLICY website_members_job_all ON website_members
        FOR ALL
        USING ({CTX} = 'job')
        WITH CHECK ({CTX} = 'job')
        """
    )


def downgrade() -> None:
    for suffix in ("job_all", "user_delete", "user_update", "user_insert", "user_read"):
        op.execute(
            f"DROP POLICY IF EXISTS website_members_{suffix} ON website_members"
        )
    op.execute("ALTER TABLE website_members DISABLE ROW LEVEL SECURITY")

    for suffix in (
        "job_all", "user_delete", "user_update", "user_insert",
        "public_read", "user_read",
    ):
        op.execute(f"DROP POLICY IF EXISTS websites_{suffix} ON websites")
    op.execute("ALTER TABLE websites DISABLE ROW LEVEL SECURITY")

    op.execute("DROP FUNCTION IF EXISTS argus_member_role(integer, text)")
