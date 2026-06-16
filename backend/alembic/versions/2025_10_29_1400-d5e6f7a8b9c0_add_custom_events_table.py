"""add custom_events table

Revision ID: d5e6f7a8b9c0
Revises: b4e5f6a7c8d9
Create Date: 2025-10-29 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = 'd5e6f7a8b9c0'
down_revision = 'b4e5f6a7c8d9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create custom_events table for flexible event tracking with properties."""
    op.create_table(
        'custom_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('website_id', sa.Integer(), nullable=False),
        sa.Column('event_name', sa.String(length=255), nullable=False),
        sa.Column('properties', JSONB, nullable=True),
        sa.Column('path', sa.String(length=2048), nullable=True),
        sa.Column('referrer', sa.String(length=2048), nullable=True),
        sa.Column('country', sa.String(length=2), nullable=True),
        sa.Column('device_type', sa.String(length=50), nullable=True),
        sa.Column('browser', sa.String(length=100), nullable=True),
        sa.Column('visitor_hash', sa.String(length=64), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['website_id'], ['websites.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for efficient querying
    op.create_index('idx_custom_events_website_timestamp', 'custom_events', ['website_id', 'timestamp'])
    op.create_index('idx_custom_events_website_event', 'custom_events', ['website_id', 'event_name'])
    op.create_index('idx_custom_events_event_timestamp', 'custom_events', ['event_name', 'timestamp'])
    op.create_index(op.f('ix_custom_events_id'), 'custom_events', ['id'])
    op.create_index(op.f('ix_custom_events_website_id'), 'custom_events', ['website_id'])
    op.create_index(op.f('ix_custom_events_event_name'), 'custom_events', ['event_name'])
    op.create_index(op.f('ix_custom_events_country'), 'custom_events', ['country'])
    op.create_index(op.f('ix_custom_events_timestamp'), 'custom_events', ['timestamp'])


def downgrade() -> None:
    """Drop custom_events table."""
    op.drop_index(op.f('ix_custom_events_timestamp'), table_name='custom_events')
    op.drop_index(op.f('ix_custom_events_country'), table_name='custom_events')
    op.drop_index(op.f('ix_custom_events_event_name'), table_name='custom_events')
    op.drop_index(op.f('ix_custom_events_website_id'), table_name='custom_events')
    op.drop_index(op.f('ix_custom_events_id'), table_name='custom_events')
    op.drop_index('idx_custom_events_event_timestamp', table_name='custom_events')
    op.drop_index('idx_custom_events_website_event', table_name='custom_events')
    op.drop_index('idx_custom_events_website_timestamp', table_name='custom_events')
    op.drop_table('custom_events')
