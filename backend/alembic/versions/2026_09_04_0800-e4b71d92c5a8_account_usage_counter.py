"""Count each account's usage per month, maintained by the database

Groundwork for per-account limits. The limit itself has to be checked on every
single pageview, which rules out counting rows: that is O(everything the
account has ever recorded) on the hottest path in the product.

So the count is kept as it happens. One row per account per calendar month,
incremented by a trigger on insert, the same arrangement as owner_email and
for the same reason: a value the application must never be able to forget to
maintain. A new tracking path added next year gets it without knowing it
exists.

Reading it is then a single primary-key lookup.

The counter is per account rather than per website deliberately. A pageview
costs the same whichever domain it came from, and someone splitting a blog, a
shop and a landing page across three domains should not be treated as three
customers.

Revision ID: e4b71d92c5a8
Revises: d3f81c62a49b
Create Date: 2026-09-04 08:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e4b71d92c5a8'
down_revision = 'd3f81c62a49b'
branch_labels = None
depends_on = None


COUNTED_TABLES = ["pageviews", "custom_events", "ecommerce_events"]


def upgrade() -> None:
    op.create_table(
        "account_usage",
        sa.Column("owner_email", sa.String(length=255), primary_key=True),
        # The first of the month, so a month is one row and the current period
        # is date_trunc('month', now()).
        sa.Column("period_start", sa.Date(), primary_key=True),
        sa.Column("events", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_count_account_usage()
        RETURNS trigger AS $$
        BEGIN
            -- owner_email is filled in by the trigger that runs before this
            -- one. If it is somehow NULL the event still records: refusing to
            -- store a customer's traffic because a counter could not be
            -- updated would be the wrong way round.
            IF NEW.owner_email IS NULL THEN
                RETURN NULL;
            END IF;

            INSERT INTO account_usage (owner_email, period_start, events, updated_at)
            VALUES (NEW.owner_email, date_trunc('month', now())::date, 1, now())
            ON CONFLICT (owner_email, period_start)
            DO UPDATE SET events = account_usage.events + 1, updated_at = now();

            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    for table in COUNTED_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_count_usage
            AFTER INSERT ON {table}
            FOR EACH ROW EXECUTE FUNCTION argus_count_account_usage();
            """
        )

    # Backfill, so a limit switched on tomorrow does not treat every existing
    # account as though it had used nothing this month.
    for table in COUNTED_TABLES:
        op.execute(
            f"""
            INSERT INTO account_usage (owner_email, period_start, events, updated_at)
            SELECT owner_email, date_trunc('month', timestamp)::date, count(*), now()
              FROM {table}
             WHERE owner_email IS NOT NULL
             GROUP BY 1, 2
            ON CONFLICT (owner_email, period_start)
            DO UPDATE SET events = account_usage.events + EXCLUDED.events
            """
        )

    # The tracking context reads it to decide whether to record, and the
    # dashboard reads it to show usage. No policies: it holds a count and an
    # address that the account already knows, and the tracking context has no
    # user to scope by.
    op.execute("GRANT SELECT, INSERT, UPDATE ON account_usage TO argus_app")


def downgrade() -> None:
    for table in COUNTED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_count_usage ON {table}")
    op.execute("DROP FUNCTION IF EXISTS argus_count_account_usage()")
    op.drop_table("account_usage")
