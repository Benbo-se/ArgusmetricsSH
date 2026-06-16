"""add pageview properties

Revision ID: a481760b5e3d
Revises: c5d7e8f9a0b1
Create Date: 2025-11-13 18:35:57.212939

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = 'a481760b5e3d'
down_revision = 'c5d7e8f9a0b1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add properties column to pageviews table
    op.add_column('pageviews', sa.Column('properties', JSONB, nullable=True))

    # Add GIN index for JSONB queries (efficient filtering)
    op.create_index(
        'idx_pageviews_properties',
        'pageviews',
        ['properties'],
        postgresql_using='gin'
    )


def downgrade() -> None:
    # Remove GIN index
    op.drop_index('idx_pageviews_properties', table_name='pageviews')

    # Remove properties column
    op.drop_column('pageviews', 'properties')
