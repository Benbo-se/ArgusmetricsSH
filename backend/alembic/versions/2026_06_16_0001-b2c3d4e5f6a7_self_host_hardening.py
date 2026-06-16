"""self-host hardening: single-use magic tokens, stripe idempotency, ecommerce idempotency

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f7
Create Date: 2026-06-16 00:01:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Single-use magic-link tokens (replay protection)
    op.create_table(
        'used_magic_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('jti', sa.String(length=64), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_used_magic_tokens_id'), 'used_magic_tokens', ['id'])
    op.create_index('ix_used_magic_tokens_jti', 'used_magic_tokens', ['jti'], unique=True)

    # Stripe webhook idempotency
    op.create_table(
        'processed_stripe_events',
        sa.Column('event_id', sa.String(length=255), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('event_id'),
    )
    op.create_index(
        op.f('ix_processed_stripe_events_event_id'),
        'processed_stripe_events', ['event_id'],
    )

    # Ecommerce purchase idempotency: one (website, transaction_id) purchase max
    op.create_index(
        'uq_ecommerce_purchase_txn',
        'ecommerce_events',
        ['website_id', 'transaction_id'],
        unique=True,
        postgresql_where=sa.text("event_type = 'purchase' AND transaction_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index('uq_ecommerce_purchase_txn', table_name='ecommerce_events')
    op.drop_index(op.f('ix_processed_stripe_events_event_id'), table_name='processed_stripe_events')
    op.drop_table('processed_stripe_events')
    op.drop_index('ix_used_magic_tokens_jti', table_name='used_magic_tokens')
    op.drop_index(op.f('ix_used_magic_tokens_id'), table_name='used_magic_tokens')
    op.drop_table('used_magic_tokens')
