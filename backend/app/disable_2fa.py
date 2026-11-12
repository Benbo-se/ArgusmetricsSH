"""Turn two-factor authentication off for one account, from the server.

On a hosted service, someone who loses their phone and their recovery codes
writes to support. A self-hosted instance has no support: the person locked
out is usually the person who runs it. Without this they would be editing
rows in psql, and getting it half right leaves an account that asks for a
code nothing can produce.

Whoever can run a command in this container already has the database, so this
grants nothing they did not have. It is deliberately not reachable over HTTP.

What it does, in one go:

  - turns two-factor authentication off and deletes the secret and every
    recovery code, including an enrolment that was started and never finished
  - lifts a lock left by too many wrong codes
  - signs the account out everywhere, because the reason for doing this may
    be that somebody else set it up

The password is untouched. The account signs in with it alone afterwards and
can set two-factor authentication up again from /dashboard/account.

    ./argus admin disable-2fa                      # asks which account
    python -m app.disable_2fa --email person@example.com
"""
import argparse
import sys

from sqlalchemy import text

from app.database import SessionLocal, set_rls_context
from app.services import two_factor
from app.utils.security import normalize_email


def run(db, email: str) -> dict:
    """Do it. Returns {} when there is no such account."""
    email = normalize_email(email)
    exists = db.execute(text("SELECT 1 FROM users WHERE email = :e"), {"e": email}).scalar()
    if not exists:
        return {}
    was_enabled = two_factor.disable(db, email)
    signed_out = two_factor.revoke_sessions(db, email)
    return {"was_enabled": was_enabled, "signed_out": signed_out}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Turn two-factor authentication off for one account."
    )
    parser.add_argument("--email", required=True, help="the account")
    args = parser.parse_args(argv)
    email = normalize_email(args.email)

    db = SessionLocal()
    # users and sessions carry no policy; declared anyway so this keeps
    # working if they ever do, like the other operator commands.
    set_rls_context(db, context="job")
    try:
        result = run(db, email)
    finally:
        db.close()

    if not result:
        print(f"No account {email}.", file=sys.stderr)
        return 1

    if result["was_enabled"]:
        print(f"Two-factor authentication is off for {email}.")
    else:
        print(
            f"{email} did not have two-factor authentication on. "
            "Any unfinished setup and any lock were cleared."
        )
    print(f"Signed out of {result['signed_out']} session(s).")
    print("The password is unchanged. It can be set up again at /dashboard/account.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
