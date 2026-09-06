"""Resolve countries from a table we build ourselves

Country lookup needed a database file from a vendor: MaxMind wants an account
and a licence key, DB-IP wants an attribution line. Neither sends visitor
addresses anywhere, so neither was a privacy problem, but both are a step in
the setup where a self-hosted product depends on somebody else's download.

The five Regional Internet Registries publish the underlying allocation data
themselves, daily, openly, with no account. That is where the vendors start
too. This table holds it.

  registry|cc|ipv4|81.224.0.0|262144|20010823|allocated

The value on an IPv4 line is a count of addresses, not a prefix length, and it
is not guaranteed to be a power of two, so a record is not always one CIDR
block. Ranges rather than networks for that reason.

Lookup is a SECURITY DEFINER function, which is what this schema already does
for everything an unauthenticated caller needs: the tracking context has no
SELECT policy on anything, deliberately, because a tracking code is public in
every customer's page source. Resolving a country must not become the one
exception that hands out a read.

What this cannot do is worth writing down next to it. RIR data says which
country a block was allocated *to*, not where it is used. For consumer ISPs
that is the same thing. For a block allocated to a US company and announced in
Stockholm it is not, which is why the vendors layer BGP data on top and why an
operator who cares about that should still point GEOIP_DB_PATH at an mmdb.

Revision ID: e1f7a3c9d84b
Revises: c3d8f0a51e72
Create Date: 2026-09-06 09:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET

from app.migration_grants import grant


revision = 'e1f7a3c9d84b'
down_revision = 'c3d8f0a51e72'
branch_labels = None
depends_on = None

CTX = "current_setting('app.context', true)"


def upgrade() -> None:
    op.create_table(
        'ip_country_ranges',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('start_ip', INET(), nullable=False),
        sa.Column('end_ip', INET(), nullable=False),
        sa.Column('country', sa.String(length=2), nullable=False),
        sa.Column('registry', sa.String(length=16), nullable=False),
        sa.Column('refreshed_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
    )

    # The lookup is "the last range that starts at or before this address".
    # With a btree on start_ip that is an index scan backwards stopping at the
    # first row, so it costs the same on three hundred thousand ranges as on
    # three hundred. Ranges do not overlap, so the first hit is the answer.
    op.create_index(
        'ix_ip_country_ranges_start', 'ip_country_ranges', ['start_ip']
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_country_for_ip(p_ip inet)
        RETURNS varchar
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT r.country
              FROM ip_country_ranges r
             WHERE r.start_ip <= p_ip
               AND r.end_ip >= p_ip
               AND family(r.start_ip) = family(p_ip)
             ORDER BY r.start_ip DESC
             LIMIT 1
        $$;
        """
    )

    # "Is there any data at all", for the dashboard's empty state. Also a
    # SECURITY DEFINER function, and for a reason that has bitten this project
    # before: development connects as the table owner, where policies are
    # inert, so a plain SELECT here would answer truthfully in development and
    # always answer "no" in production.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_country_data_loaded()
        RETURNS boolean
        LANGUAGE sql
        STABLE
        SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT EXISTS (SELECT 1 FROM ip_country_ranges)
        $$;
        """
    )

    # Reference data, not anybody's data: every row here came from a public
    # file. It still gets policies, because a table without them in a schema
    # where everything else has them is the one nobody notices later.
    op.execute("ALTER TABLE ip_country_ranges ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY ip_country_ranges_job_all ON ip_country_ranges
        FOR ALL
        USING ({CTX} = 'job')
        WITH CHECK ({CTX} = 'job')
        """
    )

    grant("SELECT, INSERT, UPDATE, DELETE", "TABLE ip_country_ranges")
    grant("USAGE, SELECT", "SEQUENCE ip_country_ranges_id_seq")
    grant("EXECUTE", "FUNCTION argus_country_for_ip(inet)")
    grant("EXECUTE", "FUNCTION argus_country_data_loaded()")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS argus_country_data_loaded()")
    op.execute("DROP FUNCTION IF EXISTS argus_country_for_ip(inet)")
    op.drop_index('ix_ip_country_ranges_start', table_name='ip_country_ranges')
    op.drop_table('ip_country_ranges')

