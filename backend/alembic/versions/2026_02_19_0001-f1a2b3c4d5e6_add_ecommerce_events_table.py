"""add ecommerce_events table

Revision ID: f1a2b3c4d5e6
Revises: 2025_11_13_2030
Create Date: 2026-02-19 00:01:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = '2025_11_13_2030'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create ecommerce_events table for revenue and product tracking."""
    # Check if table already exists (may have been created by SQLAlchemy create_all)
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'ecommerce_events')"
    ))
    if result.scalar():
        return

    op.create_table(
        'ecommerce_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('website_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('event_name', sa.String(length=255), nullable=False),
        sa.Column('transaction_id', sa.String(length=255), nullable=True),
        sa.Column('revenue', sa.DECIMAL(precision=15, scale=2), nullable=True),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='USD'),
        sa.Column('tax', sa.DECIMAL(precision=15, scale=2), nullable=True),
        sa.Column('shipping', sa.DECIMAL(precision=15, scale=2), nullable=True),
        sa.Column('product_id', sa.String(length=255), nullable=True),
        sa.Column('product_name', sa.String(length=500), nullable=True),
        sa.Column('product_category', sa.String(length=255), nullable=True),
        sa.Column('product_brand', sa.String(length=255), nullable=True),
        sa.Column('product_variant', sa.String(length=255), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=True, server_default='1'),
        sa.Column('price', sa.DECIMAL(precision=15, scale=2), nullable=True),
        sa.Column('properties', JSONB, nullable=True),
        sa.Column('visitor_hash', sa.String(length=64), nullable=False),
        sa.Column('country', sa.String(length=2), nullable=True),
        sa.Column('device_type', sa.String(length=50), nullable=True),
        sa.Column('browser', sa.String(length=100), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('utm_source', sa.String(length=255), nullable=True),
        sa.Column('utm_medium', sa.String(length=255), nullable=True),
        sa.Column('utm_campaign', sa.String(length=255), nullable=True),
        sa.Column('utm_content', sa.String(length=255), nullable=True),
        sa.Column('utm_term', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['website_id'], ['websites.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('revenue IS NULL OR revenue >= 0', name='ecommerce_revenue_positive'),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name='ecommerce_currency_valid'),
        sa.CheckConstraint(
            "event_type IN ('view_item', 'add_to_cart', 'remove_from_cart', 'begin_checkout', 'add_payment_info', 'add_shipping_info', 'purchase', 'refund')",
            name='ecommerce_event_type_valid'
        ),
    )

    # Single-column indexes
    op.create_index(op.f('ix_ecommerce_events_id'), 'ecommerce_events', ['id'])
    op.create_index(op.f('ix_ecommerce_events_website_id'), 'ecommerce_events', ['website_id'])
    op.create_index(op.f('ix_ecommerce_events_event_type'), 'ecommerce_events', ['event_type'])
    op.create_index(op.f('ix_ecommerce_events_transaction_id'), 'ecommerce_events', ['transaction_id'])
    op.create_index(op.f('ix_ecommerce_events_product_id'), 'ecommerce_events', ['product_id'])
    op.create_index(op.f('ix_ecommerce_events_visitor_hash'), 'ecommerce_events', ['visitor_hash'])
    op.create_index(op.f('ix_ecommerce_events_country'), 'ecommerce_events', ['country'])
    op.create_index(op.f('ix_ecommerce_events_device_type'), 'ecommerce_events', ['device_type'])
    op.create_index(op.f('ix_ecommerce_events_currency'), 'ecommerce_events', ['currency'])
    op.create_index(op.f('ix_ecommerce_events_timestamp'), 'ecommerce_events', ['timestamp'])

    # Composite indexes for common query patterns
    op.create_index('idx_ecommerce_website_timestamp', 'ecommerce_events', ['website_id', 'timestamp'])
    op.create_index('idx_ecommerce_revenue_queries', 'ecommerce_events', ['website_id', 'event_type', 'timestamp'])


def downgrade() -> None:
    """Drop ecommerce_events table."""
    op.drop_index('idx_ecommerce_revenue_queries', table_name='ecommerce_events')
    op.drop_index('idx_ecommerce_website_timestamp', table_name='ecommerce_events')
    op.drop_index(op.f('ix_ecommerce_events_timestamp'), table_name='ecommerce_events')
    op.drop_index(op.f('ix_ecommerce_events_currency'), table_name='ecommerce_events')
    op.drop_index(op.f('ix_ecommerce_events_device_type'), table_name='ecommerce_events')
    op.drop_index(op.f('ix_ecommerce_events_country'), table_name='ecommerce_events')
    op.drop_index(op.f('ix_ecommerce_events_visitor_hash'), table_name='ecommerce_events')
    op.drop_index(op.f('ix_ecommerce_events_product_id'), table_name='ecommerce_events')
    op.drop_index(op.f('ix_ecommerce_events_transaction_id'), table_name='ecommerce_events')
    op.drop_index(op.f('ix_ecommerce_events_event_type'), table_name='ecommerce_events')
    op.drop_index(op.f('ix_ecommerce_events_website_id'), table_name='ecommerce_events')
    op.drop_index(op.f('ix_ecommerce_events_id'), table_name='ecommerce_events')
    op.drop_table('ecommerce_events')
