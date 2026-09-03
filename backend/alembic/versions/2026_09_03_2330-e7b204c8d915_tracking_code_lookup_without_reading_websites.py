"""Resolve a tracking code without granting read access to websites

Groundwork for policies on websites. No behaviour changes here.

The tracking endpoints take a tracking_code from any visitor's browser and
have to turn it into a website. A policy cannot see a query's WHERE clause,
so any policy that lets the tracking context fetch one website by code lets
it read every row. A websites row carries verification_token,
public_share_token, public_password_hash and email_reports_recipient, and
row-level security works on rows, not columns, so there is no way to hand
back only the four fields the tracking path actually needs.

These functions are that missing column restriction. They run as the owner,
so they see the whole table, and they return only what the caller needs:

  argus_resolve_tracking_code   id, domain, is_verified, is_active
  argus_tracking_code_exists    a boolean

The second exists for a reason worth writing down. Generating a tracking code
checks the candidate for collisions. Under a policy that shows a user only
their own websites, that check would report a code as free while it belonged
to someone else, and the insert would then fail on the unique constraint. The
check has to see the whole table to be a check at all.

Both are STABLE and take no user identity, so they cannot be used to read
anything but these columns for one code. search_path is pinned, which is
mandatory for SECURITY DEFINER: without it a caller could put their own
schema ahead of public and have the function resolve "websites" to a table
they control.

Revision ID: e7b204c8d915
Revises: d4a91c05f6b2
Create Date: 2026-09-03 23:30:00.000000

"""
from alembic import op


revision = 'e7b204c8d915'
down_revision = 'd4a91c05f6b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_resolve_tracking_code(code text)
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

    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_tracking_code_exists(code text)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT EXISTS (SELECT 1 FROM websites w WHERE w.tracking_code = code)
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS argus_resolve_tracking_code(text)")
    op.execute("DROP FUNCTION IF EXISTS argus_tracking_code_exists(text)")
