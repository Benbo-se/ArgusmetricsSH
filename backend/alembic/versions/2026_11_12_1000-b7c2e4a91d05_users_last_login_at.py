"""Spara senaste inloggning på användaren

Städjobbet räknade en sessionsrad skapad inom fönstret som aktivitet, men
utloggning tar bort raden. Ett konto utan webbplats som loggat in och ut
(normaltillståndet för ett inbjudet konto) kunde därför raderas vid nästa
körning. Inloggningen får nu en egen kolumn.

Befintliga användare får nu() som senaste inloggning, så ingen plötsligt
räknas som inaktiv av den här ändringen: alla får ett nytt fönster på 30 dagar.

Revision ID: b7c2e4a91d05
Revises: a4d9e2f6b813
Create Date: 2026-11-12 10:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


revision = 'b7c2e4a91d05'
down_revision = 'a4d9e2f6b813'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET last_login_at = now()")


def downgrade() -> None:
    op.drop_column('users', 'last_login_at')
