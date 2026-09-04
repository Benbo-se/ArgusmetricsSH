"""Create the first account on a fresh instance.

An instance runs with registration closed, which is the right default: it
means nobody who finds the URL can sign up. It also means a brand new database
has no way in at all, because the one path that creates accounts is an
invitation and there is nobody to send one.

So this exists, and it is deliberately not a general "add a user" command:

  - It refuses once any account exists. After the first one, people join by
    invitation, which is the approval and leaves a record of who invited whom.
    A command that could add accounts at any time would be a way around that.
  - It never takes a password on the command line. Arguments end up in shell
    history and in `ps` output for every user on the machine.
  - The account it creates is verified, because there is no inbox to check
    against and no invitation to prove control of the address. Whoever can run
    a command inside the container already has the database.

Usage on a server:

    docker compose -f docker/docker-compose.prod.yml exec backend \\
        python -m app.bootstrap

It prompts for the address and the password. Add --email to skip the first
prompt; the password is always prompted for.
"""
import argparse
import getpass
import sys

from sqlalchemy import text

from app.database import SessionLocal
from app.services.auth_service import _hash_password
from app.utils.password_rules import failed_rules, password_ok
from app.utils.security import validate_email


def _existing_account_count(db) -> int:
    return db.execute(text("SELECT count(*) FROM users")).scalar() or 0


def _read_password() -> str:
    """Ask twice, so a typo is a retry rather than a locked-out instance."""
    while True:
        first = getpass.getpass("Password: ")
        if not first:
            print("A password is required.", file=sys.stderr)
            continue
        second = getpass.getpass("Repeat: ")
        if first != second:
            print("They do not match. Try again.", file=sys.stderr)
            continue
        return first


def create_first_account(db, email: str, password: str) -> None:
    """Insert the account, or raise ValueError saying why not."""
    email = email.strip().lower()

    if not validate_email(email):
        raise ValueError(f"{email} is not a valid email address.")

    existing = _existing_account_count(db)
    if existing:
        raise ValueError(
            f"This instance already has {existing} account(s), so there is "
            "nothing to bootstrap. Add people by inviting them from a "
            "website's Team page: the invitation is the approval, and it "
            "records who invited whom."
        )

    if not password_ok(password, email):
        raise ValueError(
            "That password does not meet the requirements: "
            + ", ".join(failed_rules(password, email))
        )

    # Written with SQL rather than the ORM so this stays usable even if the
    # model gains columns that a half-migrated database does not have yet.
    db.execute(
        text(
            "INSERT INTO users (email, is_verified, password_hash, created_at) "
            "VALUES (:e, true, :h, now())"
        ),
        {"e": email, "h": _hash_password(password)},
    )
    db.commit()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create the first account on a fresh Argusmetrics instance."
    )
    parser.add_argument(
        "--email",
        help="The address for the account. Prompted for if not given.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        existing = _existing_account_count(db)
        if existing:
            print(
                f"This instance already has {existing} account(s). "
                "Nothing to do.\n"
                "To give somebody else access, invite them from the Team page "
                "of the website they should see.",
                file=sys.stderr,
            )
            return 1

        email = args.email or input("Email: ").strip()
        password = _read_password()

        create_first_account(db, email, password)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled. Nothing was created.", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(
        f"Created {email}. Sign in at your instance's /login.\n"
        "Registration stays closed: invite anyone else from a website's Team page."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
