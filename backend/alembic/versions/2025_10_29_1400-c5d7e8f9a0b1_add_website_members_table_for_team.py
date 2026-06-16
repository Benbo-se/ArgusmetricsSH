"""add_website_members_table_for_team_collaboration

Revision ID: c5d7e8f9a0b1
Revises: b4e5f6a7c8d9
Create Date: 2025-10-29 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c5d7e8f9a0b1'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum types and table using raw SQL to avoid SQLAlchemy enum conflicts
    op.execute("DO $$ BEGIN CREATE TYPE memberrole AS ENUM ('owner', 'admin', 'viewer'); EXCEPTION WHEN duplicate_object THEN null; END $$")
    op.execute("DO $$ BEGIN CREATE TYPE memberstatus AS ENUM ('pending', 'active', 'revoked'); EXCEPTION WHEN duplicate_object THEN null; END $$")
    op.execute("""
        CREATE TABLE website_members (
            id SERIAL PRIMARY KEY,
            website_id INTEGER NOT NULL REFERENCES websites(id) ON DELETE CASCADE,
            user_email VARCHAR(255) NOT NULL,
            role memberrole NOT NULL,
            invited_by VARCHAR(255) NOT NULL REFERENCES users(email),
            invited_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            accepted_at TIMESTAMPTZ,
            status memberstatus NOT NULL,
            invite_token VARCHAR(64)
        )
    """)

    # Create indexes
    op.create_index(op.f('ix_website_members_id'), 'website_members', ['id'], unique=False)
    op.create_index(op.f('ix_website_members_website_id'), 'website_members', ['website_id'], unique=False)
    op.create_index(op.f('ix_website_members_user_email'), 'website_members', ['user_email'], unique=False)
    op.create_index(op.f('ix_website_members_invite_token'), 'website_members', ['invite_token'], unique=True)
    op.create_index('idx_website_user_unique', 'website_members', ['website_id', 'user_email'], unique=True)

    # Migrate existing website owners to website_members table
    # This ensures all current website owners have an "owner" role in the new system
    op.execute("""
        INSERT INTO website_members (website_id, user_email, role, invited_by, invited_at, accepted_at, status)
        SELECT
            id as website_id,
            user_email,
            'owner' as role,
            user_email as invited_by,
            created_at as invited_at,
            created_at as accepted_at,
            'active' as status
        FROM websites
    """)


def downgrade() -> None:
    # Drop indexes
    op.drop_index('idx_website_user_unique', table_name='website_members')
    op.drop_index(op.f('ix_website_members_invite_token'), table_name='website_members')
    op.drop_index(op.f('ix_website_members_user_email'), table_name='website_members')
    op.drop_index(op.f('ix_website_members_website_id'), table_name='website_members')
    op.drop_index(op.f('ix_website_members_id'), table_name='website_members')

    # Drop table
    op.drop_table('website_members')

    # Drop enum types
    op.execute("DROP TYPE memberstatus")
    op.execute("DROP TYPE memberrole")
