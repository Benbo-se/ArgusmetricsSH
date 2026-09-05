"""Let the tracking context complete a pageview with its scroll depth

The scroll depth is only known when the visitor leaves, and by then the
pageview row has existed since the page loaded. Something has to go back and
fill the column in.

The obvious move, an UPDATE policy for the tracking context, does not work and
the reason is worth writing down. Postgres fetches the existing rows to
evaluate an UPDATE's WHERE clause, and that fetch is governed by SELECT
policies. The tracking context has none, deliberately: a tracking code is
public in every customer's page source, and read access to pageviews would
turn it into a way to read that site's traffic. So the policy was added, the
update matched nothing, and the security tests passed while the feature did
not work.

A SECURITY DEFINER function instead, which is what this schema already does
for every other thing an unauthenticated caller needs: resolving a tracking
code, a share token, an invitation. The function runs as the table owner, and
policies never apply to an owner, so no context needs new powers.

What it can do is fixed in its body rather than granted to a caller:

  - set scroll_depth, and nothing else
  - on one row, the newest matching website, visitor and path
  - only within thirty minutes, longer than a page is read and shorter than
    the daily salt that makes a visitor hash repeat at all
  - only upward, so a page left and returned to keeps the deeper value

The visitor hash is computed on the server from the request, so the browser
holds no row id and learns nothing it was not already sending.

Revision ID: c3d8f0a51e72
Revises: b8f2a71c4e39
Create Date: 2026-09-05 12:00:00.000000

"""
from alembic import op

from app.migration_grants import grant


revision = 'c3d8f0a51e72'
down_revision = 'b8f2a71c4e39'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_complete_scroll_depth(
            p_website_id integer,
            p_visitor_hash varchar,
            p_path varchar,
            p_depth integer
        )
        RETURNS boolean
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            -- The website comes in as a parameter, so the function checks it
            -- against the context the caller declared rather than trusting it.
            -- A SECURITY DEFINER function runs as the owner, which means a
            -- parameter it does not verify is a parameter anyone who can call
            -- it may choose. The application always passes the website it just
            -- resolved from the tracking code, so this changes nothing about
            -- the normal path and closes the abnormal one.
            WITH allowed AS (
                SELECT p_website_id AS id
                 WHERE current_setting('app.context', true) = 'tracking'
                   AND p_website_id = NULLIF(current_setting('app.website_id', true), '')::integer
            ), target AS (
                SELECT pv.id, pv."timestamp"
                  FROM pageviews pv
                  JOIN allowed a ON a.id = pv.website_id
                 WHERE pv.website_id = p_website_id
                   AND pv.visitor_hash = p_visitor_hash
                   AND pv.path = p_path
                   AND pv."timestamp" > now() - INTERVAL '30 minutes'
                 ORDER BY pv."timestamp" DESC
                 LIMIT 1
            ), updated AS (
                UPDATE pageviews p
                   SET scroll_depth = p_depth
                  FROM target t
                 WHERE p.id = t.id
                   AND p."timestamp" = t."timestamp"
                   AND (p.scroll_depth IS NULL OR p.scroll_depth < p_depth)
                RETURNING 1
            )
            SELECT EXISTS (SELECT 1 FROM updated)
        $$;
        """
    )

    # The primary key is (id, timestamp) since the hypertable conversion, so
    # the update matches on both. Without that it would scan every chunk to
    # find one row.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_pageviews_complete_lookup
            ON pageviews (website_id, visitor_hash, path, "timestamp" DESC)
        """
    )

    grant("EXECUTE", "FUNCTION argus_complete_scroll_depth(integer, varchar, varchar, integer)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_pageviews_complete_lookup")
    op.execute(
        "DROP FUNCTION IF EXISTS argus_complete_scroll_depth"
        "(integer, varchar, varchar, integer)"
    )
