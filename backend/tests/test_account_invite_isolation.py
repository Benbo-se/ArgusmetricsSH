"""An account invitation, used as the role production connects as.

Everything else in test_account_invites runs as the table owner, where
row-level security is switched off. Here the whole path runs as a role the
policies apply to: the operator creating the invitation in the job context,
and the invited person, who has no context at all, opening and using it.
"""
import os
import uuid

import pytest
from app.config import pin_psycopg2
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DB_URL = os.environ.get("RLS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DB_URL,
    reason=(
        "RLS_TEST_DATABASE_URL not set; must point at a role that is neither "
        "the table owner nor a superuser. This runs in CI."
    ),
)

PASSWORD = "Str0ng-Passw0rd!x"


@pytest.fixture
def as_app_role():
    engine = create_engine(pin_psycopg2(DB_URL), future=True)
    with engine.connect() as conn:
        is_super, bypasses = conn.execute(text(
            "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )).one()
        owner = conn.execute(text(
            "SELECT tableowner FROM pg_tables WHERE tablename = 'account_invitations'"
        )).scalar()
        me = conn.execute(text("SELECT current_user")).scalar()
    assert not is_super and not bypasses and owner != me, "policies would not apply"
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def address(engine):
    email = f"rls-friend-{uuid.uuid4().hex[:8]}@example.com"
    yield email
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM account_invitations WHERE email = :e"), {"e": email})
        conn.execute(text("DELETE FROM sessions WHERE user_email = :e"), {"e": email})
        conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})


def test_invite_open_and_join_as_the_production_role(as_app_role, address):
    from app.services import account_invites

    token = account_invites.create(as_app_role, address, "operator@example.com")
    assert [i.email for i in account_invites.pending(as_app_role) if i.email == address] == [address]

    # A fresh session with no context declared, as the invited person has.
    fresh = sessionmaker(bind=as_app_role.get_bind())()
    try:
        assert account_invites.resolve(fresh, token) == address
        session = account_invites.accept(fresh, token, PASSWORD)
        assert session.user_email == address
        assert account_invites.resolve(fresh, token) is None
    finally:
        fresh.close()


def test_without_a_context_the_table_itself_is_not_readable(as_app_role, address):
    """The invited person reaches invitations only through the two functions.
    Read directly, with no context, the table is empty to them."""
    from app.services import account_invites

    account_invites.create(as_app_role, address, "operator@example.com")
    fresh = sessionmaker(bind=as_app_role.get_bind())()
    try:
        rows = fresh.execute(text("SELECT count(*) FROM account_invitations")).scalar()
        assert rows == 0
    finally:
        fresh.close()
