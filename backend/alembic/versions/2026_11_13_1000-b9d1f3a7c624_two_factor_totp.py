"""Tvåfaktorsinloggning med TOTP och återställningskoder

Fem kolumner på users och en tabell för återställningskoderna.

totp_secret_enc håller hemligheten krypterad (Fernet, nyckeln härledd ur
SECRET_KEY, se app/utils/secret_box.py). Den måste gå att läsa tillbaka för
att räkna ut koden, så en hash duger inte, men en kopia av tabellen, till
exempel i en backup, ska inte vara en lista över fungerande hemligheter.

totp_enabled_at är det som avgör om kontot kräver en kod. En hemlighet utan
totp_enabled_at är en påbörjad registrering och påverkar inte inloggningen:
den som stänger fliken halvvägs ska inte bli utelåst.

totp_last_step är det senaste tidssteg som godkänts, så att en kod inte går
att använda två gånger inom sitt giltighetsfönster. totp_failed_attempts och
totp_locked_until begränsar gissningar per konto och ligger i databasen, inte
i processen, så gränsen gäller över alla workers och överlever en omstart.

Återställningskoderna lagras bara som SHA-256. De har 80 bitars entropi, så en
osaltad hash räcker, och den är avsiktligt oberoende av SECRET_KEY: byts
nyckeln går hemligheten inte längre att läsa, men återställningskoderna
fungerar fortfarande och är då vägen in.

Varken users eller sessions har radnivåsäkerhet, eftersom inloggningen läser
dem innan någon identitet finns. Den nya tabellen läses i samma läge och
följer dem. Befintliga konton får NULL och 0 och loggar in precis som förut.

Revision ID: b9d1f3a7c624
Revises: b9e1c7a4d220
Create Date: 2026-11-13 10:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

from app.migration_grants import grant


revision = 'b9d1f3a7c624'
down_revision = 'b9e1c7a4d220'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('totp_secret_enc', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('totp_enabled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('totp_last_step', sa.BigInteger(), nullable=True))
    op.add_column(
        'users',
        sa.Column('totp_failed_attempts', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column('users', sa.Column('totp_locked_until', sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        'two_factor_recovery_codes',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'user_email', sa.String(length=255),
            sa.ForeignKey('users.email', ondelete='CASCADE'), nullable=False,
        ),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        'ix_two_factor_recovery_codes_user_email',
        'two_factor_recovery_codes', ['user_email'],
    )

    grant("SELECT, INSERT, UPDATE, DELETE", "TABLE two_factor_recovery_codes")
    grant("USAGE, SELECT", "SEQUENCE two_factor_recovery_codes_id_seq")


def downgrade() -> None:
    op.drop_index(
        'ix_two_factor_recovery_codes_user_email',
        table_name='two_factor_recovery_codes',
    )
    op.drop_table('two_factor_recovery_codes')
    op.drop_column('users', 'totp_locked_until')
    op.drop_column('users', 'totp_failed_attempts')
    op.drop_column('users', 'totp_last_step')
    op.drop_column('users', 'totp_enabled_at')
    op.drop_column('users', 'totp_secret_enc')
