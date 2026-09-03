"""Let API-token authentication resolve its user, and declare a context

Fixes a live bug, and unblocks policies on websites.

Two things authenticate a request: a session cookie and an X-API-Token
header. Only the first declared a row-level security context. The token path
resolved a user and returned without calling set_rls_context, so every
API-token request ran with no context at all.

That is not cosmetic. The traffic tables already have policies, and a request
with no context matches none of them, so it reads nothing:

    as argus_app, no context     pageviews for website 2 -> 0
    as argus_app, user context   pageviews for website 2 -> 2563

Invisible in development, where the app connects as the table owner and
policies never apply. This is the second time that gap has hidden a real
fault, which is why the cross-tenant test connects as an unprivileged role.

Fixing it needs a lookup that does not depend on the context it is trying to
establish. The token path learns who the user is by reading the token's
website, and once websites is policied that read is exactly what a
context-less request cannot do. So the resolution goes through a SECURITY
DEFINER function, as the tracking code and share token lookups do, returning
only the website id and the owner's email.

Revision ID: a8d5e2f1c904
Revises: f3c6a81b7e40
Create Date: 2026-09-04 00:30:00.000000

"""
from alembic import op


revision = 'a8d5e2f1c904'
down_revision = 'f3c6a81b7e40'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_resolve_api_token(token_hash text)
        RETURNS TABLE (website_id integer, owner_email varchar)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT t.website_id, w.user_email
              FROM api_tokens t
              JOIN websites w ON w.id = t.website_id
             WHERE t.token = token_hash
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS argus_resolve_api_token(text)")
