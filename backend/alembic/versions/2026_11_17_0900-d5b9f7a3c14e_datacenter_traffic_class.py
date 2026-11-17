"""Label traffic from hosting providers, and keep it out of the statistics (#103)

Crawlers that run JavaScript behind an ordinary Chrome user agent are counted
as visitors, and on one site they are more than half of a week. Nothing they
send gives them away. Where they send it from does, and since the address is
never stored, that has to be decided when the pageview arrives.

Five things, in the order they are made:

  hosting_network_ranges   the address ranges of the hosting providers listed
                           in app/hosting_asns.py, loaded from IPtoASN's
                           public file by a weekly job. Empty until the first
                           refresh, and an empty table classifies nothing.

  argus_traffic_class_for_ip(inet)
                           'datacenter' or NULL. SECURITY DEFINER, as
                           argus_country_for_ip is and for the same reason:
                           the tracking context reads no table, and this hands
                           it one word about an address it already holds.

  pageviews.traffic_class  NULL for ordinary traffic. Nullable and without a
                           default, so on a hypertable that is not compressed
                           this is a catalogue change: no chunk is rewritten
                           and nothing is backfilled. No index, because no
                           query selects on it alone.

  websites.exclude_datacenter
                           the per-site switch, on by default. NOT NULL with a
                           constant default, which Postgres also records in
                           the catalogue without rewriting the table.

  argus_resolve_tracking_code(text)
                           returns the switch as a sixth field, so that
                           recording knows whether anything may follow from a
                           labelled pageview without a second lookup.

And one trigger. pageviews_count_usage now fires only for rows without a
label: a pageview nobody is shown should not be charged to the account's
monthly limit either.

Taking the label off again is the downgrade: the column goes, and with it the
only record of which rows were labelled. The rows themselves stay and are
counted as ordinary traffic, which is what they were before.

Revision ID: d5b9f7a3c14e
Revises: c4a8e6f2b139
Create Date: 2026-11-17 09:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET

from app.migration_grants import grant


revision = 'd5b9f7a3c14e'
down_revision = 'c4a8e6f2b139'
branch_labels = None
depends_on = None

CTX = "current_setting('app.context', true)"


def upgrade() -> None:
    op.create_table(
        'hosting_network_ranges',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('start_ip', INET(), nullable=False),
        sa.Column('end_ip', INET(), nullable=False),
        sa.Column('refreshed_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
    )
    op.create_index(
        'ix_hosting_network_ranges_start', 'hosting_network_ranges', ['start_ip']
    )

    # Not the query argus_country_for_ip uses, although it asks the same
    # question. That one filters on end_ip while walking the index backwards,
    # which is one step in a table that covers nearly every address and a walk
    # through thousands of rows in a table that covers few: for an ordinary
    # visitor's address almost no range below it reaches that far, and the
    # scan would only stop at the bottom of the index.
    #
    # So: take the one range that starts at or before the address, then ask
    # whether it reaches. Ranges do not overlap (the loader merges them), so
    # if that one does not contain the address, none does.
    #
    # There is no check that the range and the address are of the same
    # family, and none is needed: inet orders every IPv4 address before every
    # IPv6 one. The last range below an IPv6 address may well be an IPv4 one,
    # and its end is then below the address too.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_traffic_class_for_ip(p_ip inet)
        RETURNS varchar
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT CASE WHEN r.end_ip >= p_ip THEN 'datacenter'::varchar END
              FROM (
                    SELECT h.start_ip, h.end_ip
                      FROM hosting_network_ranges h
                     WHERE h.start_ip <= p_ip
                     ORDER BY h.start_ip DESC
                     LIMIT 1
                   ) r
        $$;
        """
    )

    # Reference data from a public file. It still gets a policy, because a
    # table without one in a schema where everything else has one is the table
    # nobody notices later.
    op.execute("ALTER TABLE hosting_network_ranges ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY hosting_network_ranges_job_all ON hosting_network_ranges
        FOR ALL
        USING ({CTX} = 'job')
        WITH CHECK ({CTX} = 'job')
        """
    )

    grant("SELECT, INSERT, UPDATE, DELETE", "TABLE hosting_network_ranges")
    grant("USAGE, SELECT", "SEQUENCE hosting_network_ranges_id_seq")
    grant("EXECUTE", "FUNCTION argus_traffic_class_for_ip(inet)")

    op.add_column(
        'pageviews',
        sa.Column('traffic_class', sa.String(length=16), nullable=True),
    )
    op.add_column(
        'websites',
        sa.Column('exclude_datacenter', sa.Boolean(), nullable=False,
                  server_default=sa.text('true')),
    )

    # The return type changes, so the old signature has to go first: Postgres
    # will not replace a function whose OUT parameters differ. Both statements
    # are in the migration's transaction, so no request sees the gap, and the
    # release before this one selects its five columns by name and does not
    # mind a sixth.
    op.execute("DROP FUNCTION IF EXISTS argus_resolve_tracking_code(text)")
    op.execute(
        """
        CREATE FUNCTION argus_resolve_tracking_code(code text)
        RETURNS TABLE (
            id integer,
            domain varchar,
            is_verified boolean,
            is_active boolean,
            owner_email varchar,
            exclude_datacenter boolean
        )
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT w.id, w.domain, w.is_verified, w.is_active, w.user_email,
                   w.exclude_datacenter
              FROM websites w
             WHERE w.tracking_code = code
        $$;
        """
    )
    grant("EXECUTE", "FUNCTION argus_resolve_tracking_code(text)")

    # In the trigger and not in the application, for the reason the counter is
    # a trigger at all: a recording path added next year gets it without
    # knowing it exists.
    op.execute("DROP TRIGGER IF EXISTS pageviews_count_usage ON pageviews")
    op.execute(
        """
        CREATE TRIGGER pageviews_count_usage
        AFTER INSERT ON pageviews
        FOR EACH ROW
        WHEN (NEW.traffic_class IS NULL)
        EXECUTE FUNCTION argus_count_account_usage();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS pageviews_count_usage ON pageviews")
    op.execute(
        """
        CREATE TRIGGER pageviews_count_usage
        AFTER INSERT ON pageviews
        FOR EACH ROW EXECUTE FUNCTION argus_count_account_usage();
        """
    )

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
    grant("EXECUTE", "FUNCTION argus_resolve_tracking_code(text)")

    op.drop_column('websites', 'exclude_datacenter')
    op.drop_column('pageviews', 'traffic_class')

    op.execute("DROP FUNCTION IF EXISTS argus_traffic_class_for_ip(inet)")
    op.drop_index('ix_hosting_network_ranges_start', table_name='hosting_network_ranges')
    op.drop_table('hosting_network_ranges')
