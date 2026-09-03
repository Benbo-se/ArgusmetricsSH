"""FK ondelete rules + refund idempotency index

Every child FK was created without an ON DELETE rule, so deleting a website
that had ever received traffic raised an IntegrityError — websites were
undeletable, and account cleanup rolled back whole batches on one bad row.

Rules:
  * children of websites -> CASCADE (deleting a site removes its data)
  * sessions/websites -> users.email CASCADE (deleting a user removes both)
  * website_members.invited_by -> SET NULL (a membership must survive its
    inviter's account being deleted)

Also widens the money-event idempotency index to cover refunds, which the
schema comment already claimed.

Revision ID: 25d97005f786
Revises: a5ddac8aaee7
Create Date: 2026-09-03 12:56
"""
from alembic import op
import sqlalchemy as sa


revision = '25d97005f786'
down_revision = 'a5ddac8aaee7'
branch_labels = None
depends_on = None


# (constraint, table, column, referred table, referred column, ondelete)
CASCADE_FKS = [
    ('pageviews_website_id_fkey', 'pageviews', 'website_id', 'websites', 'id'),
    ('custom_events_website_id_fkey', 'custom_events', 'website_id', 'websites', 'id'),
    ('ecommerce_events_website_id_fkey', 'ecommerce_events', 'website_id', 'websites', 'id'),
    ('revenue_transactions_website_id_fkey', 'revenue_transactions', 'website_id', 'websites', 'id'),
    ('goals_website_id_fkey', 'goals', 'website_id', 'websites', 'id'),
    ('goal_conversions_website_id_fkey', 'goal_conversions', 'website_id', 'websites', 'id'),
    ('goal_conversions_goal_id_fkey', 'goal_conversions', 'goal_id', 'goals', 'id'),
    ('funnels_website_id_fkey', 'funnels', 'website_id', 'websites', 'id'),
    ('funnel_events_funnel_id_fkey', 'funnel_events', 'funnel_id', 'funnels', 'id'),
    ('api_tokens_website_id_fkey', 'api_tokens', 'website_id', 'websites', 'id'),
    ('alert_settings_website_id_fkey', 'alert_settings', 'website_id', 'websites', 'id'),
    ('sessions_user_email_fkey', 'sessions', 'user_email', 'users', 'email'),
    ('websites_user_email_fkey', 'websites', 'user_email', 'users', 'email'),
]


def upgrade() -> None:
    for name, table, col, ref_table, ref_col in CASCADE_FKS:
        op.drop_constraint(name, table, type_='foreignkey')
        op.create_foreign_key(name, table, ref_table, [col], [ref_col], ondelete='CASCADE')

    # invited_by: SET NULL requires a nullable column
    op.alter_column('website_members', 'invited_by',
                    existing_type=sa.String(length=255), nullable=True)
    op.drop_constraint('website_members_invited_by_fkey', 'website_members', type_='foreignkey')
    op.create_foreign_key('website_members_invited_by_fkey', 'website_members', 'users',
                          ['invited_by'], ['email'], ondelete='SET NULL')

    # Money-event idempotency now covers refunds too (both require a
    # transaction_id at the schema level).
    op.drop_index('uq_ecommerce_purchase_txn', table_name='ecommerce_events')
    op.create_index(
        'uq_ecommerce_purchase_txn', 'ecommerce_events',
        ['website_id', 'event_type', 'transaction_id'], unique=True,
        postgresql_where=sa.text("event_type IN ('purchase', 'refund') AND transaction_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index('uq_ecommerce_purchase_txn', table_name='ecommerce_events')
    op.create_index(
        'uq_ecommerce_purchase_txn', 'ecommerce_events',
        ['website_id', 'transaction_id'], unique=True,
        postgresql_where=sa.text("event_type = 'purchase' AND transaction_id IS NOT NULL"),
    )

    op.drop_constraint('website_members_invited_by_fkey', 'website_members', type_='foreignkey')
    op.create_foreign_key('website_members_invited_by_fkey', 'website_members', 'users',
                          ['invited_by'], ['email'])
    op.alter_column('website_members', 'invited_by',
                    existing_type=sa.String(length=255), nullable=False)

    for name, table, col, ref_table, ref_col in CASCADE_FKS:
        op.drop_constraint(name, table, type_='foreignkey')
        op.create_foreign_key(name, table, ref_table, [col], [ref_col])
