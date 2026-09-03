"""Drop the dead revenue_transactions table

Nothing has ever written a row to this table. The model and table were
created in the initial schema, but no code path constructs a
RevenueTransaction — the only references anywhere were the model itself,
its export in models/__init__.py, and the retention job dutifully deleting
old rows from a table that never had any.

Revenue actually lives in ecommerce_events (event_type='purchase'), which
is what the Revenue dashboard, the revenue service and the CSV export all
read. Keeping an identically-named empty table alongside it is an active
trap for anyone reading the schema.

Verified empty before writing this migration; the downgrade recreates the
table exactly as it was, so the change is reversible.

Revision ID: 3f1a7c9d2e04
Revises: 25d97005f786
Create Date: 2026-09-03 18:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3f1a7c9d2e04'
down_revision = '25d97005f786'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index('idx_revenue_website_timestamp', table_name='revenue_transactions')
    op.drop_index('ix_revenue_transactions_visitor_id', table_name='revenue_transactions')
    op.drop_index('ix_revenue_transactions_transaction_id', table_name='revenue_transactions')
    op.drop_index('ix_revenue_transactions_website_id', table_name='revenue_transactions')
    op.drop_index('ix_revenue_transactions_id', table_name='revenue_transactions')
    op.drop_table('revenue_transactions')


def downgrade() -> None:
    op.create_table(
        'revenue_transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('website_id', sa.Integer(), nullable=False),
        sa.Column('transaction_id', sa.String(length=255), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('amount', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), server_default='USD', nullable=False),
        sa.Column('product_name', sa.String(length=500), nullable=True),
        sa.Column('product_id', sa.String(length=255), nullable=True),
        sa.Column('visitor_id', sa.String(length=255), nullable=True),
        sa.Column('path', sa.String(length=2000), nullable=True),
        sa.Column('referrer', sa.String(length=2000), nullable=True),
        sa.Column('country', sa.String(length=2), nullable=True),
        sa.ForeignKeyConstraint(['website_id'], ['websites.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_revenue_transactions_id', 'revenue_transactions', ['id'])
    op.create_index('ix_revenue_transactions_website_id', 'revenue_transactions', ['website_id'])
    op.create_index('ix_revenue_transactions_transaction_id', 'revenue_transactions', ['transaction_id'])
    op.create_index('ix_revenue_transactions_visitor_id', 'revenue_transactions', ['visitor_id'])
    op.create_index('idx_revenue_website_timestamp', 'revenue_transactions', ['website_id', 'timestamp'])
