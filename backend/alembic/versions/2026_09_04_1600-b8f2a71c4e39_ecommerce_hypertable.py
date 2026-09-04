"""Move purchase deduplication out of ecommerce_events, then partition it

ecommerce_events was the one traffic table left as an ordinary Postgres table,
and not by oversight. It carried

    CREATE UNIQUE INDEX uq_ecommerce_purchase_txn
        ON ecommerce_events (website_id, event_type, transaction_id)
     WHERE event_type IN ('purchase','refund') AND transaction_id IS NOT NULL

which is what stops a shop's retry, or a customer refreshing the thank-you
page, from counting the same purchase twice. A hypertable requires every
unique index to contain the partitioning column, and adding `timestamp` to
that one would permit the same transaction again at a different time, which is
precisely what it exists to prevent. Duplicate revenue is a worse failure than
a large table, so the table stayed as it was.

This keeps the guarantee and gets the partitioning, by moving the uniqueness
somewhere it does not have to be partitioned:

    ecommerce_transactions(website_id, event_type, transaction_id)

One row per transaction, claimed before the event is written. A second attempt
hits the primary key and is refused, exactly as before, and the check no
longer has to live on a table we want to partition by time.

The claim table stays small: one narrow row per purchase, against a row per
purchase in ecommerce_events that carries revenue, currency, product details
and a visitor hash. Retention deletes from it on the same schedule, so it does
not outlive the events it protects.

Row-level security on it has two contexts and not four, because only two
things touch it: the tracking path inserts, and the retention job deletes.
Nothing reads it in a user or public context, so no policy grants that. It
holds no revenue and nothing a report would want.

Revision ID: b8f2a71c4e39
Revises: a7c4e91b3d52
Create Date: 2026-09-04 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

from app.migration_grants import grant


revision = 'b8f2a71c4e39'
down_revision = 'a7c4e91b3d52'
branch_labels = None
depends_on = None


CHUNK_INTERVAL = "7 days"


def upgrade() -> None:
    op.create_table(
        "ecommerce_transactions",
        sa.Column("website_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("transaction_id", sa.String(length=255), nullable=False),
        sa.Column(
            "first_seen",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["website_id"], ["websites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("website_id", "event_type", "transaction_id"),
    )

    # Retention deletes by age, so that is what needs an index.
    op.create_index(
        "ix_ecommerce_transactions_first_seen", "ecommerce_transactions", ["first_seen"]
    )

    # Every transaction already recorded keeps its claim, so the events that
    # exist today are still protected from a duplicate arriving tomorrow.
    # DISTINCT ON because the old index permitted one row per key and this
    # table permits exactly the same, but a database restored from before the
    # index existed could hold more.
    op.execute(
        """
        INSERT INTO ecommerce_transactions
                    (website_id, event_type, transaction_id, first_seen)
        SELECT DISTINCT ON (website_id, event_type, transaction_id)
               website_id, event_type, transaction_id, min("timestamp") OVER (
                   PARTITION BY website_id, event_type, transaction_id
               )
          FROM ecommerce_events
         WHERE event_type IN ('purchase', 'refund')
           AND transaction_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )

    # Only now: the hypertable cannot be created while this index exists.
    op.execute("DROP INDEX IF EXISTS uq_ecommerce_purchase_txn")

    op.execute("ALTER TABLE ecommerce_events DROP CONSTRAINT ecommerce_events_pkey")
    op.execute('ALTER TABLE ecommerce_events ADD PRIMARY KEY (id, "timestamp")')

    op.execute(
        f"""
        SELECT create_hypertable(
            'ecommerce_events', 'timestamp',
            chunk_time_interval => INTERVAL '{CHUNK_INTERVAL}',
            migrate_data => true,
            if_not_exists => true
        )
        """
    )

    op.execute("ALTER TABLE ecommerce_transactions ENABLE ROW LEVEL SECURITY")

    # The tracking path claims a transaction and never reads one back: a
    # duplicate announces itself as a unique violation, which Postgres raises
    # whether or not the conflicting row would have been visible. That is what
    # lets the tracking context stay write-only.
    op.execute(
        """
        CREATE POLICY ecommerce_transactions_tracking_write
            ON ecommerce_transactions FOR INSERT
            WITH CHECK (
                current_setting('app.context', true) = 'tracking'
                AND website_id = NULLIF(current_setting('app.website_id', true), '')::integer
            )
        """
    )
    op.execute(
        """
        CREATE POLICY ecommerce_transactions_job_all
            ON ecommerce_transactions FOR ALL
            USING (current_setting('app.context', true) = 'job')
            WITH CHECK (current_setting('app.context', true) = 'job')
        """
    )

    grant("SELECT, INSERT, DELETE", "ecommerce_transactions")


def downgrade() -> None:
    """Refuses, for the same reason as the first hypertable migration.

    There is no operation that turns a hypertable back into an ordinary table,
    and the copy-and-swap recipe silently loses the row-level security
    policies and the owner_email trigger. Restore the pre-migration backup.
    """
    raise NotImplementedError(
        "Converting ecommerce_events back to a plain table cannot be done "
        "without losing its policies and triggers. Restore the pre-migration "
        "backup instead."
    )
