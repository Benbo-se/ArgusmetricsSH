"""Resolve an invitation token without a row-level security context

Fixes invitation links, broken by the website_members policies.

Someone opening an invitation link is not logged in yet, and may not even have
an account. There is no user to declare a context for, so the lookup matched
no policy and every link reported "Invitation not found or already accepted".
As argus_app:

    no context declared   get_invite_details -> refused
    with a context        get_invite_details -> the website

The invitation token is itself the credential, exactly like a tracking code or
a share token, so it gets the same treatment: a SECURITY DEFINER function that
takes the token and returns only what the invitation page shows.

The row it returns is a pending invitation and nothing else. An accepted or
revoked one resolves to nothing, so a used link cannot be replayed to read a
website's name back out.

Revision ID: d92f7b3e5a18
Revises: b6e419af7c23
Create Date: 2026-09-04 02:00:00.000000

"""
from alembic import op


revision = 'd92f7b3e5a18'
down_revision = 'b6e419af7c23'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_resolve_invite_token(token text)
        RETURNS TABLE (
            website_name varchar,
            website_domain varchar,
            role text,
            invited_by varchar,
            invited_at timestamptz,
            invitee_email varchar
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT w.name, w.domain, m.role::text, m.invited_by,
                   m.invited_at, m.user_email
              FROM website_members m
              JOIN websites w ON w.id = m.website_id
             WHERE m.invite_token = token
               AND m.status = 'pending'::memberstatus
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS argus_resolve_invite_token(text)")
