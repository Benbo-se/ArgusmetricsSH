"""Addresses of people who want to be told when hosted signup opens

Registration is closed on argusmetrics.io, and until now every "Get started
free" button led to a redirect back to the login page. The button worked, the
route worked, and nothing told the visitor anything: they clicked and stayed
where they were.

The page that replaces that redirect asks for an address instead of pretending
to be a form. Which means storing one, and an email address is personal data
whether or not it arrived voluntarily. So this table holds the least that can
answer the question it exists for: the address, when it arrived, and which
page it came from. No name, no IP, no user agent, nothing that would let this
become a second visitor log inside a product whose argument is that it does
not keep one.

Read only by the job context and by an authenticated operator. There is no
policy that lets an unauthenticated caller read it: the endpoint that writes
to it is public, and a public endpoint that could also read would turn the
waiting list into a list anyone could download.

Revision ID: f2b8c4e91a37
Revises: e1f7a3c9d84b
Create Date: 2026-09-06 17:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

from app.migration_grants import grant


revision = 'f2b8c4e91a37'
down_revision = 'e1f7a3c9d84b'
branch_labels = None
depends_on = None

CTX = "current_setting('app.context', true)"


def upgrade() -> None:
    op.create_table(
        'waitlist',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('email', sa.String(length=255), nullable=False, unique=True),
        sa.Column('source', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_waitlist_created_at', 'waitlist', ['created_at'])

    # Joining is a public action, so the insert goes through a SECURITY DEFINER
    # function rather than a policy. The same reasoning as everywhere else in
    # this schema: the caller is unauthenticated, and the way to let it do one
    # specific thing is to write that thing down in a function rather than to
    # hand it a policy it could be steered into using for something else.
    #
    # Returns true for a new address and false for one already there, so the
    # caller can answer identically either way and the page cannot be used to
    # find out whether an address is on the list.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_join_waitlist(
            p_email varchar,
            p_source varchar
        )
        RETURNS boolean
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
        DECLARE
            inserted boolean;
        BEGIN
            INSERT INTO waitlist (email, source)
            VALUES (lower(trim(p_email)), p_source)
            ON CONFLICT (email) DO NOTHING;
            GET DIAGNOSTICS inserted = ROW_COUNT;
            RETURN inserted;
        END
        $$;
        """
    )

    op.execute("ALTER TABLE waitlist ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY waitlist_job_all ON waitlist
        FOR ALL
        USING ({CTX} = 'job')
        WITH CHECK ({CTX} = 'job')
        """
    )
    # An operator signed in to the dashboard may read it. Deliberately not the
    # public or tracking contexts: the endpoint that writes here is open to
    # anyone, and a read policy reachable from it would publish the list.
    op.execute(
        f"""
        CREATE POLICY waitlist_user_read ON waitlist
        FOR SELECT
        USING ({CTX} = 'user')
        """
    )

    grant("SELECT, INSERT, UPDATE, DELETE", "TABLE waitlist")
    grant("USAGE, SELECT", "SEQUENCE waitlist_id_seq")
    grant("EXECUTE", "FUNCTION argus_join_waitlist(varchar, varchar)")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS argus_join_waitlist(varchar, varchar)")
    op.drop_index('ix_waitlist_created_at', table_name='waitlist')
    op.drop_table('waitlist')
