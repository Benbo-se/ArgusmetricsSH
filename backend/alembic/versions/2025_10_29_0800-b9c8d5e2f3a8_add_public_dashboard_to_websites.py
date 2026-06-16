"""add_public_dashboard_to_websites

Revision ID: b9c8d5e2f3a8
Revises: a3416caf1bf9
Create Date: 2025-10-29 08:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b9c8d5e2f3a8'
down_revision = 'a3416caf1bf9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add public dashboard fields to websites table
    op.add_column('websites', sa.Column('is_public', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('websites', sa.Column('public_share_token', sa.String(length=32), nullable=True))

    # Create unique index on public_share_token (only for non-null values)
    op.create_index(op.f('ix_websites_public_share_token'), 'websites', ['public_share_token'], unique=True)


def downgrade() -> None:
    # Drop index
    op.drop_index(op.f('ix_websites_public_share_token'), table_name='websites')

    # Drop columns
    op.drop_column('websites', 'public_share_token')
    op.drop_column('websites', 'is_public')
