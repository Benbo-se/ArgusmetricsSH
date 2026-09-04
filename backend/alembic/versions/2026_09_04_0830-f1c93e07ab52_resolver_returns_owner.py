"""The tracking-code resolver also returns the owner

The monthly limit is per account, so deciding whether to record an event needs
to know whose account it is. The resolver already joins websites to find the
row; returning one more column from that join is free, and the alternative is
a second query on the hottest path in the product.

Still narrower than the table: id, domain, is_verified, is_active and now
user_email. Not the tracking code, not the verification token, not the share
token, not the password hash.

Revision ID: f1c93e07ab52
Revises: e4b71d92c5a8
Create Date: 2026-09-04 08:30:00.000000

"""
from alembic import op


revision = 'f1c93e07ab52'
down_revision = 'e4b71d92c5a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The return type changes, so the old signature has to go first: Postgres
    # will not replace a function whose OUT parameters differ.
    op.execute("DROP FUNCTION IF EXISTS argus_resolve_tracking_code(text)")
    op.execute(
        """
        CREATE FUNCTION argus_resolve_tracking_code(code text)
        RETURNS TABLE (
            id integer,
            domain varchar,
            is_verified boolean,
            is_active boolean,
            owner_email varchar
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT w.id, w.domain, w.is_verified, w.is_active, w.user_email
              FROM websites w
             WHERE w.tracking_code = code
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS argus_resolve_tracking_code(text)")
    op.execute(
        """
        CREATE FUNCTION argus_resolve_tracking_code(code text)
        RETURNS TABLE (id integer, domain varchar, is_verified boolean, is_active boolean)
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT w.id, w.domain, w.is_verified, w.is_active
              FROM websites w
             WHERE w.tracking_code = code
        $$;
        """
    )
