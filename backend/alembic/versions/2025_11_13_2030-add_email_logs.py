"""add email_logs table

Revision ID: 2025_11_13_2030
Revises: a481760b5e3d
Create Date: 2025-11-13 20:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2025_11_13_2030'
down_revision: Union[str, None] = 'a481760b5e3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add email_logs table for tracking all sent emails."""
    op.create_table(
        'email_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('to_email', sa.String(length=255), nullable=False),
        sa.Column('email_type', sa.String(length=50), nullable=False),
        sa.Column('subject', sa.String(length=500), nullable=True),
        sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False, default=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_email_logs_to_email', 'email_logs', ['to_email'])
    op.create_index('ix_email_logs_email_type', 'email_logs', ['email_type'])
    op.create_index('ix_email_logs_sent_at', 'email_logs', ['sent_at'])


def downgrade() -> None:
    """Remove email_logs table."""
    op.drop_index('ix_email_logs_sent_at', table_name='email_logs')
    op.drop_index('ix_email_logs_email_type', table_name='email_logs')
    op.drop_index('ix_email_logs_to_email', table_name='email_logs')
    op.drop_table('email_logs')
