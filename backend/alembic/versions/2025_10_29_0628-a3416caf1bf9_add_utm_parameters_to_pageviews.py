"""add_utm_parameters_to_pageviews

Revision ID: a3416caf1bf9
Revises: 7c3f2e3a43af
Create Date: 2025-10-29 06:28:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a3416caf1bf9'
down_revision = '7c3f2e3a43af'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add UTM parameter columns to pageviews table
    op.add_column('pageviews', sa.Column('utm_source', sa.String(length=255), nullable=True))
    op.add_column('pageviews', sa.Column('utm_medium', sa.String(length=255), nullable=True))
    op.add_column('pageviews', sa.Column('utm_campaign', sa.String(length=255), nullable=True))
    op.add_column('pageviews', sa.Column('utm_content', sa.String(length=255), nullable=True))
    op.add_column('pageviews', sa.Column('utm_term', sa.String(length=255), nullable=True))

    # Create indexes for UTM columns for faster querying
    op.create_index(op.f('ix_pageviews_utm_source'), 'pageviews', ['utm_source'], unique=False)
    op.create_index(op.f('ix_pageviews_utm_medium'), 'pageviews', ['utm_medium'], unique=False)
    op.create_index(op.f('ix_pageviews_utm_campaign'), 'pageviews', ['utm_campaign'], unique=False)


def downgrade() -> None:
    # Drop indexes
    op.drop_index(op.f('ix_pageviews_utm_campaign'), table_name='pageviews')
    op.drop_index(op.f('ix_pageviews_utm_medium'), table_name='pageviews')
    op.drop_index(op.f('ix_pageviews_utm_source'), table_name='pageviews')

    # Drop columns
    op.drop_column('pageviews', 'utm_term')
    op.drop_column('pageviews', 'utm_content')
    op.drop_column('pageviews', 'utm_campaign')
    op.drop_column('pageviews', 'utm_medium')
    op.drop_column('pageviews', 'utm_source')
