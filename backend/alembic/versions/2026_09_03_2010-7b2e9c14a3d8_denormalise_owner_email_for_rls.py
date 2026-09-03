"""Denormalise owner_email onto the traffic tables, for row-level security

Step 1 of the RLS rollout. No policies are created here: this only puts the
column in place so the policies that follow can be an indexed equality check.

Why denormalise at all: these tables reach their owner through websites, and
funnel_events through funnels as well. A policy expressed as a join would run
that join for every row on every read, forever, on exactly the tables that
grow with traffic rather than with configuration.

Scope is deliberately the five traffic tables. goals, funnels, api_tokens,
alert_settings and website_members hold a handful of rows each and grow with
how a customer configures things, so a join there costs nothing and an extra
column would only be something else to keep in sync.

The value is maintained by triggers rather than by application code. It is a
security-relevant column: a NULL merely hides rows, but a wrong value would
expose one tenant's data to another. A trigger cannot be forgotten by a new
code path, a bulk import or a manual fix over psql, and a second trigger on
websites propagates an ownership change to every child row.

Revision ID: 7b2e9c14a3d8
Revises: 3f1a7c9d2e04
Create Date: 2026-09-03 20:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '7b2e9c14a3d8'
down_revision = '3f1a7c9d2e04'
branch_labels = None
depends_on = None


# Tables that reach websites directly through website_id
VIA_WEBSITE = ["pageviews", "custom_events", "ecommerce_events", "goal_conversions"]


def upgrade() -> None:
    # 1. Add the column, nullable for now so the backfill has somewhere to land.
    for table in VIA_WEBSITE + ["funnel_events"]:
        op.add_column(table, sa.Column("owner_email", sa.String(length=255), nullable=True))

    # 2. Backfill from the current owner.
    for table in VIA_WEBSITE:
        op.execute(
            f"""
            UPDATE {table} t
               SET owner_email = w.user_email
              FROM websites w
             WHERE w.id = t.website_id
            """
        )
    op.execute(
        """
        UPDATE funnel_events fe
           SET owner_email = w.user_email
          FROM funnels f
          JOIN websites w ON w.id = f.website_id
         WHERE f.id = fe.funnel_id
        """
    )

    # 3. Keep it correct from here on. Deriving the value in the database means
    #    no insert path can set it wrong, including ones written later.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_set_owner_email_from_website()
        RETURNS trigger AS $$
        BEGIN
            SELECT w.user_email INTO NEW.owner_email
              FROM websites w
             WHERE w.id = NEW.website_id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_set_owner_email_from_funnel()
        RETURNS trigger AS $$
        BEGIN
            SELECT w.user_email INTO NEW.owner_email
              FROM funnels f
              JOIN websites w ON w.id = f.website_id
             WHERE f.id = NEW.funnel_id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in VIA_WEBSITE:
        op.execute(
            f"""
            CREATE TRIGGER {table}_set_owner_email
            BEFORE INSERT OR UPDATE OF website_id ON {table}
            FOR EACH ROW EXECUTE FUNCTION argus_set_owner_email_from_website();
            """
        )
    op.execute(
        """
        CREATE TRIGGER funnel_events_set_owner_email
        BEFORE INSERT OR UPDATE OF funnel_id ON funnel_events
        FOR EACH ROW EXECUTE FUNCTION argus_set_owner_email_from_funnel();
        """
    )

    # 4. If a website changes hands, its rows must follow.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION argus_propagate_owner_email()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.user_email IS DISTINCT FROM OLD.user_email THEN
                UPDATE pageviews        SET owner_email = NEW.user_email WHERE website_id = NEW.id;
                UPDATE custom_events    SET owner_email = NEW.user_email WHERE website_id = NEW.id;
                UPDATE ecommerce_events SET owner_email = NEW.user_email WHERE website_id = NEW.id;
                UPDATE goal_conversions SET owner_email = NEW.user_email WHERE website_id = NEW.id;
                UPDATE funnel_events fe SET owner_email = NEW.user_email
                  FROM funnels f WHERE f.id = fe.funnel_id AND f.website_id = NEW.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER websites_propagate_owner_email
        AFTER UPDATE OF user_email ON websites
        FOR EACH ROW EXECUTE FUNCTION argus_propagate_owner_email();
        """
    )

    # 5. Index it: this is the column every policy will filter on. Named the way
    #    SQLAlchemy names an index=True column, so autogenerate sees no drift.
    for table in VIA_WEBSITE + ["funnel_events"]:
        op.create_index(f"ix_{table}_owner_email", table, ["owner_email"])


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS websites_propagate_owner_email ON websites")
    op.execute("DROP FUNCTION IF EXISTS argus_propagate_owner_email()")
    op.execute("DROP TRIGGER IF EXISTS funnel_events_set_owner_email ON funnel_events")
    for table in VIA_WEBSITE:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_set_owner_email ON {table}")
    op.execute("DROP FUNCTION IF EXISTS argus_set_owner_email_from_website()")
    op.execute("DROP FUNCTION IF EXISTS argus_set_owner_email_from_funnel()")
    for table in VIA_WEBSITE + ["funnel_events"]:
        op.drop_index(f"ix_{table}_owner_email", table_name=table)
        op.drop_column(table, "owner_email")
