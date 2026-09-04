"""Drop seventeen duplicate indexes

Every table carried a redundant index on its primary key. A primary key
already has a unique index, and the models asked for a second one:

    id = Column(Integer, primary_key=True, index=True)

Repeated in fifteen model files, covering sixteen tables. api_tokens had a
seventeenth: a non-unique index on token beside the unique one that
unique=True already creates.

Every index has to be maintained on every insert. On the configuration tables
that is noise. On pageviews, custom_events and ecommerce_events it is a write
cost paid on every single visitor event, forever, buying nothing, and the
pages compete for cache with indexes that are actually used.

Found with a query rather than by eye, which is the only reason all seventeen
are here. I noticed the one on pageviews and assumed it was a one-off:

    SELECT i1.tablename, i1.indexname, i2.indexname
    FROM pg_indexes i1
    JOIN pg_indexes i2
      ON i1.tablename = i2.tablename AND i1.indexname <> i2.indexname
     AND regexp_replace(i1.indexdef, '^.*USING ', '')
       = regexp_replace(i2.indexdef, '^.*USING ', '')
    WHERE i1.schemaname = 'public' AND i1.indexname > i2.indexname;

Worth doing before any table becomes a hypertable, since that rewrites the
indexes and there is no reason to pay to rebuild these.

Revision ID: c9e5b1a73d28
Revises: f7a2b60c8e91
Create Date: 2026-09-04 04:00:00.000000

"""
from alembic import op


revision = 'c9e5b1a73d28'
down_revision = 'f7a2b60c8e91'
branch_labels = None
depends_on = None


# Every one of these duplicates that table's primary key index.
DUPLICATE_ID_INDEXES = [
    ("alert_settings", "ix_alert_settings_id"),
    ("api_tokens", "ix_api_tokens_id"),
    ("custom_events", "ix_custom_events_id"),
    ("ecommerce_events", "ix_ecommerce_events_id"),
    ("email_logs", "ix_email_logs_id"),
    ("funnel_events", "ix_funnel_events_id"),
    ("funnels", "ix_funnels_id"),
    ("goal_conversions", "ix_goal_conversions_id"),
    ("goals", "ix_goals_id"),
    ("pageviews", "ix_pageviews_id"),
    ("sessions", "ix_sessions_id"),
    ("used_magic_tokens", "ix_used_magic_tokens_id"),
    ("users", "ix_users_id"),
    ("website_members", "ix_website_members_id"),
    ("websites", "ix_websites_id"),
]


def upgrade() -> None:
    for table, index in DUPLICATE_ID_INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {index}")

    # The unique ix_api_tokens_token stays: it enforces uniqueness and serves
    # the lookup by hash. This one only ever duplicated it.
    op.execute("DROP INDEX IF EXISTS idx_api_tokens_token")


def downgrade() -> None:
    for table, index in DUPLICATE_ID_INDEXES:
        op.create_index(index, table, ["id"])
    op.create_index("idx_api_tokens_token", "api_tokens", ["token"])
