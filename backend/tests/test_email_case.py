"""Email addresses are the same address whatever their capitalisation.

Signup and login compared addresses as typed, team invitations stored them as
typed and accepted them lowercased, and account invitations lowercased
everywhere. So `Anna@x.com` invited to a site became the account `anna@x.com`
with a membership under a different spelling, and an address could register
twice by changing a capital.
"""
import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from app.models.website_member import MemberRole
from app.services.auth_service import AuthService
from app.services.team_service import TeamService

PASSWORD = "a-long-enough-password-9"


@pytest.fixture
def stem():
    return uuid.uuid4().hex[:8]


def _count_users(db, lowered):
    return db.execute(
        text("SELECT count(*) FROM users WHERE lower(email) = :e"), {"e": lowered}
    ).scalar()


def test_a_team_invitation_to_a_mixed_case_address_gives_working_access(db, website, stem):
    invited = f"Anna.{stem}@Example.com"
    lowered = invited.lower()

    result = TeamService(db).invite_member(
        website["id"], website["email"], invited, MemberRole.VIEWER
    )
    token = result["invite_url"].split("token=")[1]
    AuthService(db).create_account_from_invitation(invite_token=token, password=PASSWORD)

    assert _count_users(db, lowered) == 1
    assert TeamService(db).check_website_access(lowered, website["id"]) is not None, (
        "the account exists but its membership is stored under another spelling"
    )


def test_inviting_the_same_address_in_another_case_is_a_duplicate(db, website, stem):
    service = TeamService(db)
    service.invite_member(website["id"], website["email"], f"bob.{stem}@example.com", MemberRole.VIEWER)
    with pytest.raises(ValueError, match="pending"):
        service.invite_member(
            website["id"], website["email"], f"BOB.{stem}@Example.com", MemberRole.VIEWER
        )


def test_signup_in_another_case_does_not_make_a_second_account(db, stem):
    service = AuthService(db)
    service.signup_user(f"Carl.{stem}@Example.com", PASSWORD)
    service.signup_user(f"carl.{stem}@example.com", PASSWORD)

    assert _count_users(db, f"carl.{stem}@example.com") == 1
    stored = db.execute(
        text("SELECT email FROM users WHERE lower(email) = :e"),
        {"e": f"carl.{stem}@example.com"},
    ).scalar()
    assert stored == stored.lower(), "the address was stored as typed"


def test_login_ignores_the_case_of_the_address(db, stem):
    email = f"dana.{stem}@example.com"
    service = AuthService(db)
    service.signup_user(email, PASSWORD)
    db.execute(text("UPDATE users SET is_verified = true WHERE email = :e"), {"e": email})
    db.commit()

    session = service.login_user(f"Dana.{stem}@EXAMPLE.com", PASSWORD)

    assert session.user_email == email


# The migration that lowercases what is already stored.

def _migration():
    path = next(
        (Path(__file__).parent.parent / "alembic" / "versions").glob("*_lowercase_email_addresses.py")
    )
    spec = importlib.util.spec_from_file_location("lowercase_email_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _user(db, email):
    db.execute(
        text("INSERT INTO users (email, is_verified, created_at) VALUES (:e, true, now())"),
        {"e": email},
    )


def test_the_migration_refuses_when_two_accounts_would_become_one(db, stem):
    _user(db, f"Eve.{stem}@example.com")
    _user(db, f"eve.{stem}@example.com")

    with pytest.raises(RuntimeError) as refused:
        _migration().lowercase_all(db.connection())

    message = str(refused.value)
    assert f"Eve.{stem}@example.com" in message and f"eve.{stem}@example.com" in message
    assert _count_users(db, f"eve.{stem}@example.com") == 2, "it merged or changed something anyway"


def test_the_migration_lowercases_an_account_and_everything_pointing_at_it(db, stem):
    mixed = f"Finn.{stem}@Example.com"
    lowered = mixed.lower()
    _user(db, mixed)
    db.execute(
        text(
            "INSERT INTO websites (name, domain, user_email, tracking_code,"
            "  verification_token, is_verified, is_active, email_reports_enabled,"
            "  is_public, public_password_enabled, created_at) "
            "VALUES ('s', :d, :e, :tc, :vt, true, true, false, false, false, now())"
        ),
        {"d": f"https://{stem}.example.com", "e": mixed, "tc": stem, "vt": f"t-{stem}"},
    )
    db.execute(
        text(
            "INSERT INTO sessions (token, user_email, expires_at) "
            "VALUES (:t, :e, now() + interval '1 day')"
        ),
        {"t": f"s-{stem}", "e": mixed},
    )
    db.execute(
        text(
            "INSERT INTO website_members (website_id, user_email, owner_email, role,"
            "  status, invited_by, invited_at) "
            "SELECT id, :u, :o, 'viewer', 'pending', :o, now() FROM websites WHERE tracking_code = :tc"
        ),
        {"u": f"Gus.{stem}@Example.com", "o": mixed, "tc": stem},
    )

    _migration().lowercase_all(db.connection())

    assert db.execute(text("SELECT email FROM users WHERE lower(email) = :e"), {"e": lowered}).scalar() == lowered
    assert db.execute(text("SELECT user_email FROM websites WHERE tracking_code = :t"), {"t": stem}).scalar() == lowered
    assert db.execute(text("SELECT user_email FROM sessions WHERE token = :t"), {"t": f"s-{stem}"}).scalar() == lowered
    row = db.execute(
        text("SELECT user_email, owner_email, invited_by FROM website_members WHERE owner_email = :o"),
        {"o": lowered},
    ).one()
    assert row == (f"gus.{stem}@example.com", lowered, lowered)
