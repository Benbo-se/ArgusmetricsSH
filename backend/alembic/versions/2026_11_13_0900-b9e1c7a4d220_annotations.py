"""Anteckningar på tidslinjen

En anteckning är ett datum och en rad text på en webbplats graf ("ny
startsida", "kampanj start"), så att en förändring går att förklara i
efterhand.

Datumet är en DATE, inte en tidpunkt. Det är ett dygn i webbplatsens tidszon,
samma dygn som grafens punkter räknas i, så det behöver aldrig räknas om och
flyttar sig inte om någon byter zon på webbplatsen.

Radnivåsäkerheten följer goals och funnels (f7a2b60c8e91) med två skillnader:

  läsa    ägaren, eller en aktiv medlem
  skriva  ägaren, eller en aktiv admin

  - spårningen har ingen policy: den behöver aldrig läsa en anteckning
  - den publika delningslänken har ingen policy: en anteckning är en
    arbetsanteckning för teamet och visas inte för den som bara har länken

Utan policy läser de kontexterna ingenting, vilket är meningen.

Revision ID: b9e1c7a4d220
Revises: a6c2d8e4f913
Create Date: 2026-11-13 09:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

from app.migration_grants import grant


revision = 'b9e1c7a4d220'
down_revision = 'a6c2d8e4f913'
branch_labels = None
depends_on = None


ME = "current_setting('app.user_email', true)"
CTX = "current_setting('app.context', true)"
OWNER = "argus_website_owner(website_id) = " + ME
MEMBER = "argus_member_role(website_id, " + ME + ") IS NOT NULL"
ADMIN = "argus_member_role(website_id, " + ME + ") = 'admin'"


def upgrade() -> None:
    op.create_table(
        'annotations',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('website_id', sa.Integer(),
                  sa.ForeignKey('websites.id', ondelete='CASCADE'), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('note', sa.String(length=200), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('idx_annotations_website_day', 'annotations', ['website_id', 'day'])

    op.execute("ALTER TABLE annotations ENABLE ROW LEVEL SECURITY")

    op.execute(
        f"""
        CREATE POLICY annotations_user_read ON annotations
        FOR SELECT
        USING ({CTX} = 'user' AND ({OWNER} OR {MEMBER}))
        """
    )
    op.execute(
        f"""
        CREATE POLICY annotations_user_insert ON annotations
        FOR INSERT
        WITH CHECK ({CTX} = 'user' AND ({OWNER} OR {ADMIN}))
        """
    )
    # WITH CHECK ser den nya raden, så en anteckning kan inte heller flyttas
    # till en webbplats man inte får skriva på.
    op.execute(
        f"""
        CREATE POLICY annotations_user_update ON annotations
        FOR UPDATE
        USING ({CTX} = 'user' AND ({OWNER} OR {ADMIN}))
        WITH CHECK ({CTX} = 'user' AND ({OWNER} OR {ADMIN}))
        """
    )
    op.execute(
        f"""
        CREATE POLICY annotations_user_delete ON annotations
        FOR DELETE
        USING ({CTX} = 'user' AND ({OWNER} OR {ADMIN}))
        """
    )
    op.execute(
        f"""
        CREATE POLICY annotations_job_all ON annotations
        FOR ALL
        USING ({CTX} = 'job')
        WITH CHECK ({CTX} = 'job')
        """
    )

    grant("SELECT, INSERT, UPDATE, DELETE", "TABLE annotations")
    grant("USAGE, SELECT", "SEQUENCE annotations_id_seq")


def downgrade() -> None:
    op.drop_index('idx_annotations_website_day', table_name='annotations')
    op.drop_table('annotations')
