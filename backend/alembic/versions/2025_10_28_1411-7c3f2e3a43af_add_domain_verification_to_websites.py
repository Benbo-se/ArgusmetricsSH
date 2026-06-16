"""add_domain_verification_to_websites

Revision ID: 7c3f2e3a43af
Revises: 55ea4a9600a0
Create Date: 2025-10-28 14:11:52.537958

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7c3f2e3a43af'
down_revision = '55ea4a9600a0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add verification fields to websites table
    op.add_column('websites', sa.Column('verification_token', sa.String(length=64), nullable=True))
    op.add_column('websites', sa.Column('is_verified', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('websites', sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True))

    # Create index on is_verified for faster queries
    op.create_index(op.f('ix_websites_is_verified'), 'websites', ['is_verified'], unique=False)

    # Generate verification tokens for existing websites
    op.execute("""
        UPDATE websites
        SET verification_token = md5(random()::text || domain || now()::text)
        WHERE verification_token IS NULL
    """)

    # Make verification_token NOT NULL after generating values
    op.alter_column('websites', 'verification_token', nullable=False)

    # Create unique index on verification_token
    op.create_index(op.f('ix_websites_verification_token'), 'websites', ['verification_token'], unique=True)


def downgrade() -> None:
    # Drop indexes
    op.drop_index(op.f('ix_websites_verification_token'), table_name='websites')
    op.drop_index(op.f('ix_websites_is_verified'), table_name='websites')

    # Drop columns
    op.drop_column('websites', 'verified_at')
    op.drop_column('websites', 'is_verified')
    op.drop_column('websites', 'verification_token')
