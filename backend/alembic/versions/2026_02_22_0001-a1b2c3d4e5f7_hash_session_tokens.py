"""hash session tokens - clear plaintext sessions

Revision ID: a1b2c3d4e5f7
Revises: f1a2b3c4d5e6
Create Date: 2026-02-22 00:01:00.000000

"""
from typing import Sequence, Union
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Clear all existing sessions — they contain plaintext tokens
    # that can't be converted to hashes. All users will need to log in again.
    op.execute("DELETE FROM sessions")


def downgrade() -> None:
    # No-op: can't restore deleted sessions
    pass
