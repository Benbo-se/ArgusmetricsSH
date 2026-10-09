"""Invitations to an account of one's own, for an instance with signup closed

Registration is closed on argusmetrics.io, and the only way in was an
invitation to somebody else's website: the invited person got an account,
but only as a member of a site that was not theirs. Somebody who wanted to try
Argus on their own site had to be let into the operator's first.

An account invitation is the operator naming an address, and nothing more.
Accepting it creates an account with no websites, and the person adds their
own. Registration stays closed: the invitation is the approval, as it already
is for team invitations.

Only a SHA-256 of the token is stored. The token is a credential that creates
an account, and a copy of this table, in a backup for instance, should not be
a list of working links.

Read and written only in the job context (the operator's admin page and the
cleanup). The person accepting is not signed in and has no context to declare,
so the two things they need, looking an invitation up and using it, are
SECURITY DEFINER functions that do exactly that and no more: an invitation
resolves only while it is unused and unexpired, and it can be used once.

Revision ID: a4d9e2f6b813
Revises: f2b8c4e91a37
Create Date: 2026-10-09 09:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

from app.migration_grants import grant


revision = 'a4d9e2f6b813'
down_revision = 'f2b8c4e91a37'
branch_labels = None
depends_on = None

CTX = "current_setting('app.context', true)"


def upgrade() -> None:
    op.create_table(
        'account_invitations',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False, unique=True),
        sa.Column('invited_by', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_account_invitations_email', 'account_invitations', ['email'])

    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_resolve_account_invite(p_token_hash varchar)
        RETURNS TABLE (email varchar, expires_at timestamptz)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT i.email, i.expires_at
              FROM account_invitations i
             WHERE i.token_hash = p_token_hash
               AND i.accepted_at IS NULL
               AND i.expires_at > now()
        $$;
        """
    )
    # Marks the invitation used and returns its address, or NULL if it was
    # not usable. One statement, so two tabs submitting the same link cannot
    # both get an address back.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_use_account_invite(p_token_hash varchar)
        RETURNS varchar
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            UPDATE account_invitations
               SET accepted_at = now()
             WHERE token_hash = p_token_hash
               AND accepted_at IS NULL
               AND expires_at > now()
            RETURNING email
        $$;
        """
    )

    op.execute("ALTER TABLE account_invitations ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY account_invitations_job_all ON account_invitations
        FOR ALL
        USING ({CTX} = 'job')
        WITH CHECK ({CTX} = 'job')
        """
    )

    grant("SELECT, INSERT, UPDATE, DELETE", "TABLE account_invitations")
    grant("USAGE, SELECT", "SEQUENCE account_invitations_id_seq")
    grant("EXECUTE", "FUNCTION argus_resolve_account_invite(varchar)")
    grant("EXECUTE", "FUNCTION argus_use_account_invite(varchar)")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS argus_use_account_invite(varchar)")
    op.execute("DROP FUNCTION IF EXISTS argus_resolve_account_invite(varchar)")
    op.drop_index('ix_account_invitations_email', table_name='account_invitations')
    op.drop_table('account_invitations')
