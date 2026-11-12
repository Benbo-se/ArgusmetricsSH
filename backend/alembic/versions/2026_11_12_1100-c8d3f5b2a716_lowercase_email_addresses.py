"""Små bokstäver i alla lagrade e-postadresser

Registrering och inloggning jämförde adresser som de skrevs, teaminbjudningar
lagrade dem som de skrevs men accepterades med små bokstäver, och
kontoinbjudningar använde små bokstäver överallt. En inbjudan till
`Anna@x.com` gav kontot `anna@x.com` med ett medlemskap under en annan
stavning, och samma adress kunde registreras två gånger. Koden normaliserar nu
vid skrivning (`normalize_email`); den här migrationen gör samma sak med det som
redan finns.

Den vägrar köra, högljutt och med adresserna, om två konton eller två
medlemskap på samma webbplats skulle bli samma rad av att bli små. Att slå ihop
konton är ett beslut för en människa, inte för en migration. Åtgärd: ta bort
eller döp om en av raderna för hand (`./argus delete-user --email ...`) och kör
om.

Främmande nycklar mot users(email) flaggas tillfälligt som deferrable så att
alla tabeller kan uppdateras i samma transaktion, och sätts tillbaka efteråt.
Bara rader som inte redan är små bokstäver rörs.

Revision ID: c8d3f5b2a716
Revises: b7c2e4a91d05
Create Date: 2026-11-12 11:00:00.000000

"""
from alembic import op
from sqlalchemy import text


revision = 'c8d3f5b2a716'
down_revision = 'b7c2e4a91d05'
branch_labels = None
depends_on = None

# (table, column) holding the address of a user. Event tables carry the owner
# of the website for row-level security, so they must follow the user.
COLUMNS = [
    ("users", "email"),
    ("websites", "user_email"),
    ("sessions", "user_email"),
    ("website_members", "user_email"),
    ("website_members", "owner_email"),
    ("website_members", "invited_by"),
    ("account_usage", "owner_email"),
    ("pageviews", "owner_email"),
    ("custom_events", "owner_email"),
    ("ecommerce_events", "owner_email"),
    ("goal_conversions", "owner_email"),
    ("funnel_events", "owner_email"),
]

# Foreign keys that point at users(email) and so have to move together with it.
FOREIGN_KEYS = [
    ("sessions", "sessions_user_email_fkey"),
    ("websites", "websites_user_email_fkey"),
    ("website_members", "website_members_invited_by_fkey"),
]


def collisions(conn):
    """Groups of addresses that are one address once lowercased."""
    found = []
    for (email_list,) in conn.execute(
        text(
            "SELECT array_agg(email ORDER BY email) FROM users "
            " GROUP BY lower(email) HAVING count(*) > 1"
        )
    ):
        found.append("users: " + ", ".join(email_list))
    for site, email_list in conn.execute(
        text(
            "SELECT website_id, array_agg(user_email ORDER BY user_email) "
            "  FROM website_members "
            " GROUP BY website_id, lower(user_email) HAVING count(*) > 1"
        )
    ):
        found.append(f"website_members on website {site}: " + ", ".join(email_list))
    return found


def lowercase_all(conn):
    clashes = collisions(conn)
    if clashes:
        raise RuntimeError(
            "Migrationen avbröts: dessa adresser blir samma adress med små "
            "bokstäver och skulle slås ihop. Inget har ändrats. Ta bort eller "
            "döp om en av raderna för hand och kör om.\n  " + "\n  ".join(clashes)
        )

    for table, constraint in FOREIGN_KEYS:
        conn.execute(text(f"ALTER TABLE {table} ALTER CONSTRAINT {constraint} DEFERRABLE INITIALLY IMMEDIATE"))
    conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))

    for table, column in COLUMNS:
        conn.execute(
            text(f"UPDATE {table} SET {column} = lower({column}) WHERE {column} <> lower({column})")
        )

    # Fires the deferred foreign key checks now, before the flags go back.
    conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    for table, constraint in FOREIGN_KEYS:
        conn.execute(text(f"ALTER TABLE {table} ALTER CONSTRAINT {constraint} NOT DEFERRABLE"))


def upgrade() -> None:
    lowercase_all(op.get_bind())


def downgrade() -> None:
    # The original capitalisation is not kept, and nothing needs it back.
    pass
