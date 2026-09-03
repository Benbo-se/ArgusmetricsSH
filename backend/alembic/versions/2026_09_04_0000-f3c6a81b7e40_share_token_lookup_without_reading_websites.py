"""Resolve a public share token without granting read access to websites

The other half of the tracking-code change. Same problem: a public dashboard
is anonymous, the share token arrives in the URL, and a policy cannot see a
query's WHERE clause, so permitting the lookup permits reading every website.

The public path needs more of the row than the tracking path does, because it
renders a dashboard and may have to check a password. Six fields, taken from
what the routes actually use:

    id, name, domain, is_public, public_password_enabled, public_password_hash

What it does not return is the point: user_email, tracking_code,
verification_token, verified_at and the email report settings stay out of
reach of an anonymous viewer.

The password hash is in there because verifying a password needs it, and the
hashing lives in the application rather than the database. It never leaves the
server.

search_path is pinned, as on the tracking-code functions and for the same
reason.

Revision ID: f3c6a81b7e40
Revises: e7b204c8d915
Create Date: 2026-09-04 00:00:00.000000

"""
from alembic import op


revision = 'f3c6a81b7e40'
down_revision = 'e7b204c8d915'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_resolve_share_token(token text)
        RETURNS TABLE (
            id integer,
            name varchar,
            domain varchar,
            is_public boolean,
            public_password_enabled boolean,
            public_password_hash varchar
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT w.id, w.name, w.domain, w.is_public,
                   w.public_password_enabled, w.public_password_hash
              FROM websites w
             WHERE w.public_share_token = token
               AND w.is_public = true
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS argus_resolve_share_token(text)")
