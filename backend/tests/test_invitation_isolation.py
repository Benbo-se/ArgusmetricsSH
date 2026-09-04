"""Accepting an invitation, as the role production actually connects as.

The rest of the invitation tests run as the table owner, which is what
development connects as, and row-level security policies never apply to a
table's owner. So they prove the flow works with the policies switched off.

That is precisely how this bug would hide. `accept_invitation` reads and
updates website_members, which is policied, and the endpoint has no
authenticated caller to declare a context from. With none declared, the
pending row matches no policy: as the production role it is simply not there.
The account would be created, the invitation would silently fail to accept,
and the person would sign in to an empty dashboard.

This connects as the unprivileged role and does the whole thing for real.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DB_URL = os.environ.get("RLS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DB_URL,
    reason=(
        "RLS_TEST_DATABASE_URL not set; must point at a role that is neither "
        "the table owner nor a superuser. This runs in CI. If it is skipping "
        "there, it is testing nothing."
    ),
)

PASSWORD = "Str0ng-Passw0rd!x"


@pytest.fixture(scope="module")
def unprivileged_engine():
    engine = create_engine(DB_URL, future=True)
    with engine.connect() as conn:
        role, is_super, bypasses = conn.execute(
            text(
                "SELECT current_user,"
                "       (SELECT rolsuper FROM pg_roles WHERE rolname = current_user),"
                "       (SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user)"
            )
        ).one()
        assert not is_super, f"{role} is a superuser; policies would not apply."
        assert not bypasses, f"{role} has BYPASSRLS; policies would not apply."
        owner = conn.execute(
            text("SELECT tableowner FROM pg_tables WHERE tablename = 'website_members'")
        ).scalar()
        assert owner != role, (
            f"{role} owns website_members; policies never apply to a table's "
            "owner, so this would prove nothing."
        )
    return engine


@pytest.fixture
def pending_invitation(engine):
    """An owner, a website and a pending invitation, committed for real.

    Committed rather than left in a test transaction because the flow under
    test runs on a different connection, and an uncommitted row is invisible
    to it. Cleaned up afterwards by address.
    """
    suffix = uuid.uuid4().hex[:8]
    owner_email = f"owner-{suffix}@example.com"
    invitee_email = f"invitee-{suffix}@example.com"
    token = f"invtok-{uuid.uuid4().hex}"

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (email, is_verified, created_at) "
                "VALUES (:e, true, now())"
            ),
            {"e": owner_email},
        )
        website_id = conn.execute(
            text(
                "INSERT INTO websites (name, domain, user_email, tracking_code,"
                "                      verification_token, is_verified, is_active,"
                "                      email_reports_enabled, is_public,"
                "                      public_password_enabled, created_at) "
                "VALUES (:n, :d, :o, :tc, :vt, true, true, false, false, false, now()) "
                "RETURNING id"
            ),
            {
                "n": f"Invite site {suffix}",
                "d": f"https://invite-{suffix}.example.com",
                "o": owner_email,
                "tc": uuid.uuid4().hex[:8],
                "vt": f"tok-{suffix}",
            },
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO website_members (website_id, user_email, owner_email,"
                "                             role, status, invite_token,"
                "                             invited_by, invited_at) "
                "VALUES (:w, :u, :o, 'viewer', 'pending', :t, :o, now())"
            ),
            {"w": website_id, "u": invitee_email, "o": owner_email, "t": token},
        )

    yield {"token": token, "invitee": invitee_email, "website_id": website_id}

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM website_members WHERE user_email = :e"),
            {"e": invitee_email},
        )
        conn.execute(text("DELETE FROM websites WHERE id = :w"), {"w": website_id})
        conn.execute(
            text("DELETE FROM users WHERE email IN (:a, :b)"),
            {"a": owner_email, "b": invitee_email},
        )


def test_the_invitation_is_actually_accepted(unprivileged_engine, pending_invitation):
    """The assertion the owner-connected tests cannot make.

    Checks the membership is active, read back on the same unprivileged
    connection, which is the only way to know the update landed rather than
    matching no rows and reporting success.
    """
    from app.services.auth_service import AuthService

    Session = sessionmaker(bind=unprivileged_engine)
    session = Session()

    try:
        result = AuthService(session).create_account_from_invitation(
            invite_token=pending_invitation["token"], password=PASSWORD
        )
        assert result is not None, "no session was created"

        # Reading back needs a context of its own: the commit inside the flow
        # cleared the one it declared, which is how set_config(is_local=true)
        # behaves and is exactly why the flow must not read after committing.
        # A later request would declare its own context the same way.
        session.execute(
            text(
                "SELECT set_config('app.context', 'user', true),"
                "       set_config('app.user_email', :e, true)"
            ),
            {"e": pending_invitation["invitee"]},
        )

        status = session.execute(
            text(
                "SELECT status FROM website_members "
                " WHERE user_email = :e AND website_id = :w"
            ),
            {"e": pending_invitation["invitee"], "w": pending_invitation["website_id"]},
        ).scalar()

        assert status is not None, (
            "the membership row is invisible to the role that just updated it: "
            "no row-level security context was declared"
        )
        assert str(status).lower().endswith("active"), (
            f"the invitation was not accepted, it is still {status}. The account "
            "exists and the dashboard will be empty."
        )
    finally:
        session.rollback()
        session.close()


def test_the_account_exists_and_is_verified(unprivileged_engine, pending_invitation):
    from app.services.auth_service import AuthService

    Session = sessionmaker(bind=unprivileged_engine)
    session = Session()

    try:
        AuthService(session).create_account_from_invitation(
            invite_token=pending_invitation["token"], password=PASSWORD
        )
        verified = session.execute(
            text("SELECT is_verified FROM users WHERE email = :e"),
            {"e": pending_invitation["invitee"]},
        ).scalar()
        assert verified is True
    finally:
        session.rollback()
        session.close()
