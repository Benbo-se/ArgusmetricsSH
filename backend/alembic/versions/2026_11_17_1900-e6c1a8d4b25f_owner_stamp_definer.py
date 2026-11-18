"""Rows recorded by the tracker get their owner, and are counted

Every traffic table carries owner_email, filled in by a trigger from the
website's row, and a second trigger counts the row against the owner's month.
Neither had ever happened for a row recorded by the tracker.

The trigger function read `websites` with the rights of whoever inserted the
row. That is the tracking context, which by design can read no table at all,
so the lookup found nothing and owner_email was left NULL. The counter then
skipped the row, as it is written to do for a row without an owner. Rows
written by a signed-in user or a job got both, which is why every test passed:
development and the ordinary test suite connect as the table owner, where no
policy applies.

On the instance where this was found, every pageview since the first one had
no owner and account_usage had no rows. Nothing was exposed by it. Reports are
served through the website's membership, not through this column. What did not
work was the monthly limit, which counted nothing and so could never be
reached.

Three things:

  the two functions run with their owner's rights (SECURITY DEFINER, with a
  pinned search_path), as every other lookup the tracking context needs
  already does. They read one address by a website id the row already holds
  and write it into that row; nothing is returned to the caller.

  the rows already stored get their owner. An UPDATE of owner_email alone,
  which fires neither trigger.

  account_usage is rebuilt from the rows, since what it holds was counted
  only for the rows that happened to have an owner. Pageviews labelled as
  coming from a hosting provider are left out, as the counting trigger leaves
  them out.

Revision ID: e6c1a8d4b25f
Revises: d5b9f7a3c14e
Create Date: 2026-11-17 19:00:00.000000

"""
from alembic import op


revision = 'e6c1a8d4b25f'
down_revision = 'd5b9f7a3c14e'
branch_labels = None
depends_on = None

VIA_WEBSITE = ["pageviews", "custom_events", "ecommerce_events", "goal_conversions", "website_members"]

FROM_WEBSITE = """
    CREATE OR REPLACE FUNCTION argus_set_owner_email_from_website()
    RETURNS trigger AS $$
    BEGIN
        SELECT w.user_email INTO NEW.owner_email
          FROM websites w
         WHERE w.id = NEW.website_id;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql {rights};
"""

FROM_FUNNEL = """
    CREATE OR REPLACE FUNCTION argus_set_owner_email_from_funnel()
    RETURNS trigger AS $$
    BEGIN
        SELECT w.user_email INTO NEW.owner_email
          FROM funnels f
          JOIN websites w ON w.id = f.website_id
         WHERE f.id = NEW.funnel_id;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql {rights};
"""

DEFINER = "SECURITY DEFINER SET search_path = pg_catalog, public"


def upgrade() -> None:
    op.execute(FROM_WEBSITE.format(rights=DEFINER))
    op.execute(FROM_FUNNEL.format(rights=DEFINER))

    for table in VIA_WEBSITE:
        op.execute(
            f"""
            UPDATE {table} t
               SET owner_email = w.user_email
              FROM websites w
             WHERE w.id = t.website_id
               AND t.owner_email IS DISTINCT FROM w.user_email
            """
        )
    op.execute(
        """
        UPDATE funnel_events fe
           SET owner_email = w.user_email
          FROM funnels f
          JOIN websites w ON w.id = f.website_id
         WHERE f.id = fe.funnel_id
           AND fe.owner_email IS DISTINCT FROM w.user_email
        """
    )

    # Rebuilt whole, in the same transaction, so there is no moment when a
    # month reads as empty. A row recorded while this runs waits for the lock
    # its own counting takes and lands on top of the rebuilt figure.
    op.execute("LOCK TABLE account_usage IN EXCLUSIVE MODE")
    op.execute("DELETE FROM account_usage")
    op.execute(
        """
        INSERT INTO account_usage (owner_email, period_start, events, updated_at)
        SELECT owner_email, period_start, sum(events), now()
          FROM (
                SELECT owner_email, date_trunc('month', "timestamp")::date AS period_start,
                       count(*) AS events
                  FROM pageviews
                 WHERE owner_email IS NOT NULL AND traffic_class IS NULL
                 GROUP BY 1, 2
                UNION ALL
                SELECT owner_email, date_trunc('month', "timestamp")::date, count(*)
                  FROM custom_events
                 WHERE owner_email IS NOT NULL
                 GROUP BY 1, 2
                UNION ALL
                SELECT owner_email, date_trunc('month', "timestamp")::date, count(*)
                  FROM ecommerce_events
                 WHERE owner_email IS NOT NULL
                 GROUP BY 1, 2
               ) counted
         GROUP BY 1, 2
        """
    )


def downgrade() -> None:
    # The functions go back to the caller's rights. The owners that were
    # filled in and the rebuilt counts stay: they are true, and taking them
    # away again would only make the data wrong in the old way.
    op.execute(FROM_WEBSITE.format(rights=""))
    op.execute(FROM_FUNNEL.format(rights=""))
