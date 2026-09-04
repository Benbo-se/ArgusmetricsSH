"""Turn the traffic tables into hypertables

The TimescaleDB extension has been installed and doing nothing since the
beginning: the image provides it, the extension is enabled, and every traffic
table was an ordinary Postgres table. The single largest scalability lever
available was switched off.

What conversion buys, in order of how much it matters here:

  - Queries that look at the last 30 days stop touching older data at all,
    because the planner excludes chunks by time. That is most dashboard
    queries.
  - Retention becomes dropping a chunk instead of deleting several million
    rows one batch at a time.

Compression is deliberately not enabled, and this is not a matter of taste.
TimescaleDB refuses it outright on a table with row-level security:

    ERROR: columnstore cannot be used on table with row security

Every one of these tables has four policies, and those policies are the
guarantee that one customer cannot read another's traffic. They are what the
data processing agreement describes, what test_tenant_isolation proves against
an unprivileged role, and the reason a bug in application code cannot leak
across tenants. Storage is cheap and that guarantee is not for sale, so the
tables stay uncompressed. Anyone who later finds this and reaches for
`ALTER TABLE ... SET (timescaledb.compress)` will have to drop the policies to
do it, and that is the trade being refused here.

Four of the five tables convert. ecommerce_events does not, and the reason is
not an oversight:

    uq_ecommerce_purchase_txn enforces one purchase per transaction_id per
    website. A hypertable requires every unique index to contain the
    partitioning column, and adding `timestamp` to that index would permit the
    same transaction_id twice at different times, which is precisely what the
    index exists to prevent. Duplicate revenue is a worse failure than a large
    table. Keeping the guarantee and converting as well needs the uniqueness
    moved into a small side table, which is its own change with its own risk
    to the purchase path, so it is filed separately.

Primary keys change from (id) to (id, timestamp) on the four, for the same
requirement. Nothing references these tables by foreign key, which is what
makes that safe: they are leaves.

Everything else has to survive the conversion and is verified rather than
assumed, in test_hypertables:

  - The row-level security policies, four per table. They are what stops one
    customer reading another's traffic, and the tests connect as the
    unprivileged role to prove it still holds on chunks.
  - The BEFORE INSERT trigger that fills owner_email. The policies read that
    column, so a trigger that stopped firing would not raise an error, it
    would quietly write rows nobody can see.
  - The AFTER INSERT trigger that counts usage per account.

Revision ID: a7c4e91b3d52
Revises: f1c93e07ab52
Create Date: 2026-09-04 09:00:00.000000

"""
from alembic import op


revision = 'a7c4e91b3d52'
down_revision = 'f1c93e07ab52'
branch_labels = None
depends_on = None


# Not ecommerce_events. See the module docstring.
HYPERTABLES = ["pageviews", "custom_events", "goal_conversions", "funnel_events"]

# Seven days. At the volumes this product sees, a chunk then holds a week of
# one instance's traffic, which keeps chunk count low enough that planning
# stays cheap and small enough that dropping one is a meaningful amount of
# retention. The interval can be changed later for new chunks without
# rewriting old ones.
CHUNK_INTERVAL = "7 days"

def upgrade() -> None:
    for table in HYPERTABLES:
        # A hypertable requires the partitioning column in every unique index.
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {table}_pkey")
        op.execute(f'ALTER TABLE {table} ADD PRIMARY KEY (id, "timestamp")')

        # migrate_data moves the existing rows into chunks. It rewrites the
        # table and takes an exclusive lock, which is why this belongs in a
        # maintenance window on a populated database.
        op.execute(
            f"""
            SELECT create_hypertable(
                '{table}', 'timestamp',
                chunk_time_interval => INTERVAL '{CHUNK_INTERVAL}',
                migrate_data => true,
                if_not_exists => true
            )
            """
        )


def downgrade() -> None:
    """There is no safe automatic downgrade, so this refuses rather than lies.

    TimescaleDB has no operation that turns a hypertable back into an ordinary
    table. The usual recipe is to copy the rows into a new table and swap the
    names, and the reason that is not written here is that the copy silently
    loses the two things this schema depends on most:

      - `CREATE TABLE ... (LIKE ... INCLUDING ALL)` copies columns, defaults,
        constraints and indexes. It does not copy triggers, so owner_email
        would stop being filled in, and it does not copy row-level security
        policies, so the new table would be readable across tenants. Neither
        failure raises an error. Both are silent.
      - Reconstructing them here would duplicate definitions that live in
        earlier migrations, and the copy would drift from the original the
        first time one of those changed.

    A downgrade that quietly turns off row-level security is worse than no
    downgrade. To actually go back, restore the pre-migration dump: that
    restores the policies and the triggers with the data, which is the only
    way to be sure they came back.
    """
    raise NotImplementedError(
        "Converting hypertables back to plain tables cannot be done without "
        "losing the row-level security policies and the owner_email trigger. "
        "Restore the pre-migration backup instead. See this migration's "
        "downgrade() docstring for the reasoning."
    )
