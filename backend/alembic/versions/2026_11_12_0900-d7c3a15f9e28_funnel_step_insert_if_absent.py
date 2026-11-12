"""Record a funnel step once per visitor, from the tracking context

The recording service checked funnel_events for an existing row before adding
one. The tracking context may insert into that table and may not read it, so
the check found nothing in production and every pageview on a step path added
a row. The statistics count distinct visitors, so the numbers were right and
the table grew. In development the application connects as the table owner,
where the policies are inert, which is why nothing there showed it.

Granting the tracking context a SELECT policy would answer the question and
break the reason it has none: a tracking code is public in every customer's
page source. So the check and the insert move into a SECURITY DEFINER function,
as for the scroll depth (c3d8f0a51e72). It runs as the table owner, where
policies do not apply, and what it may do is fixed in its body:

  - insert one funnel_events row, and nothing else
  - only when the tracking context is scoped to the website the funnel
    belongs to
  - only when no row exists for that funnel, visitor and step

There is no unique index to back it. Existing tables hold the duplicates this
bug made, and an index would refuse to build. Two requests for the same visitor
in the same instant may still both insert; that is the same bound as before
and the statistics count distinct visitors.

Revision ID: d7c3a15f9e28
Revises: a4d9e2f6b813
Create Date: 2026-11-12 09:00:00.000000

"""
from alembic import op

from app.migration_grants import grant


revision = 'd7c3a15f9e28'
down_revision = 'd9e4a6c3b827'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_record_funnel_step(
            p_funnel_id integer,
            p_visitor_id varchar,
            p_step_number integer,
            p_step_name varchar,
            p_path varchar,
            p_completed boolean
        )
        RETURNS boolean
        LANGUAGE sql
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            -- The funnel arrives as a parameter, so it is checked against the
            -- website the caller's context is scoped to rather than trusted.
            WITH allowed AS (
                SELECT f.id
                  FROM funnels f
                 WHERE f.id = p_funnel_id
                   AND current_setting('app.context', true) = 'tracking'
                   AND f.website_id = NULLIF(current_setting('app.website_id', true), '')::integer
            ), inserted AS (
                INSERT INTO funnel_events
                    (funnel_id, visitor_id, step_number, step_name, path, completed)
                SELECT a.id, p_visitor_id, p_step_number, p_step_name, p_path, p_completed
                  FROM allowed a
                 WHERE NOT EXISTS (
                    SELECT 1 FROM funnel_events fe
                     WHERE fe.funnel_id = a.id
                       AND fe.visitor_id = p_visitor_id
                       AND fe.step_number = p_step_number
                 )
                RETURNING 1
            )
            SELECT EXISTS (SELECT 1 FROM inserted)
        $$;
        """
    )

    grant(
        "EXECUTE",
        "FUNCTION argus_record_funnel_step(integer, varchar, integer, varchar, varchar, boolean)",
    )


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS argus_record_funnel_step"
        "(integer, varchar, integer, varchar, varchar, boolean)"
    )
