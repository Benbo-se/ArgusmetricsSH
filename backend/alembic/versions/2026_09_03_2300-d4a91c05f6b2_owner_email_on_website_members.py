"""Denormalise owner_email onto website_members, to break a policy cycle

Groundwork, not policies. Nothing changes behaviour here.

website_members and websites want to reference each other. A website is
visible to its owner and to its members, which reaches into website_members;
a membership is visible to the member and to the website's owner, which
reaches back into websites. Postgres does not tolerate that:

    SELECT count(*) FROM websites
      -> infinite recursion detected in policy for relation "websites"

Not a degraded result. A hard error on every query against both tables. This
was reproduced against a scratch copy of the schema before writing any of it.

Carrying the owner on the membership row breaks the cycle: website_members
can then be policed without naming websites at all, so the reference goes one
way only and the recursion has nowhere to form.

Same shape as the traffic tables, for the same reasons. The value comes from
a trigger rather than application code, because a NULL would only hide a row
while a wrong value would show one team's membership list to another. The
propagate trigger on websites gains this table too, so a website changing
hands still updates every row that names its owner.

Revision ID: d4a91c05f6b2
Revises: c1f83a6d4e27
Create Date: 2026-09-03 23:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4a91c05f6b2'
down_revision = 'c1f83a6d4e27'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "website_members",
        sa.Column("owner_email", sa.String(length=255), nullable=True),
    )

    op.execute(
        """
        UPDATE website_members m
           SET owner_email = w.user_email
          FROM websites w
         WHERE w.id = m.website_id
        """
    )

    # The same function the traffic tables use: it reads NEW.website_id, which
    # this table also has.
    op.execute(
        """
        CREATE TRIGGER website_members_set_owner_email
        BEFORE INSERT OR UPDATE OF website_id ON website_members
        FOR EACH ROW EXECUTE FUNCTION argus_set_owner_email_from_website();
        """
    )

    # Extend the existing propagation to cover this table. Replacing the
    # function keeps the trigger on websites as it is.
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
                UPDATE website_members  SET owner_email = NEW.user_email WHERE website_id = NEW.id;
                UPDATE funnel_events fe SET owner_email = NEW.user_email
                  FROM funnels f WHERE f.id = fe.funnel_id AND f.website_id = NEW.id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.create_index(
        "ix_website_members_owner_email", "website_members", ["owner_email"]
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS website_members_set_owner_email ON website_members"
    )
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
    op.drop_index("ix_website_members_owner_email", table_name="website_members")
    op.drop_column("website_members", "owner_email")
