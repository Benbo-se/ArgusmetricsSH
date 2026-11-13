"""Teaminbjudningarnas token lagras som kondensat

website_members.invite_token höll själva token ur inbjudningslänken. Den
håller nu dess SHA-256, som kontoinbjudningar och sessioner redan gör.
Kolumnen är 64 tecken och ett hexkondensat är precis 64, så den ändras inte.

Väntande inbjudningar skrivs om på plats, så länkar som redan är skickade
fortsätter att fungera: koden räknar samma kondensat ur länkens token. En
token är 43 tecken (token_urlsafe(32)), så längden skiljer en rad som inte är
omskriven från en som är det, och uppgraderingen går att köra två gånger.

Nedgraderingen kan inte räkna tillbaka en token ur dess kondensat. Den lämnar
raderna som de är: den äldre koden jämför då länkens token mot ett kondensat,
hittar ingenting, och de väntande inbjudningarna får skickas om.

Revision ID: c4a8e6f2b139
Revises: b9d1f3a7c624
Create Date: 2026-11-13 18:00:00.000000

"""
from alembic import op


revision = 'c4a8e6f2b139'
down_revision = 'b9d1f3a7c624'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE website_members
           SET invite_token = encode(sha256(convert_to(invite_token, 'UTF8')), 'hex')
         WHERE invite_token IS NOT NULL
           AND length(invite_token) < 64
        """
    )


def downgrade() -> None:
    # Nothing to undo that can be undone: see the note above.
    pass
