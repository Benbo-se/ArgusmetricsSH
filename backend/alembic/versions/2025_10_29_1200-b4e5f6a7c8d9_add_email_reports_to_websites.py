"""add_email_reports_to_websites

Revision ID: b4e5f6a7c8d9
Revises: a3416caf1bf9
Create Date: 2025-10-29 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4e5f6a7c8d9'
down_revision = 'b9c8d5e2f3a8'  # Points to public dashboard migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add email reports configuration columns to websites table
    op.add_column('websites', sa.Column('email_reports_enabled', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('websites', sa.Column('email_reports_frequency', sa.String(length=20), nullable=True))
    op.add_column('websites', sa.Column('email_reports_recipient', sa.String(length=255), nullable=True))
    op.add_column('websites', sa.Column('email_reports_day', sa.Integer(), nullable=True))

    # Create index for enabled column for faster queries
    op.create_index(op.f('ix_websites_email_reports_enabled'), 'websites', ['email_reports_enabled'], unique=False)


def downgrade() -> None:
    # Drop index
    op.drop_index(op.f('ix_websites_email_reports_enabled'), table_name='websites')

    # Drop columns
    op.drop_column('websites', 'email_reports_day')
    op.drop_column('websites', 'email_reports_recipient')
    op.drop_column('websites', 'email_reports_frequency')
    op.drop_column('websites', 'email_reports_enabled')
