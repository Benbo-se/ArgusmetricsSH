"""Delete an account and everything that belongs to it, on request.

There was no way to do this except by hand in psql (docs/data-map.md, #144),
and by hand it was incomplete: website_members.user_email is not a foreign
key, so a deleted user's memberships of other people's websites stayed behind
with their address in them.

What goes, in one transaction:

  - the account, and through its foreign keys its sessions and every website
    it owns, with all of those websites' recorded traffic, goals, funnels,
    tokens, team and settings
  - its memberships of websites other people own
  - its monthly usage counter

It shows exactly that, with counts, and asks for the address to be typed again
before doing it. The address is the confirmation because it is what is being
erased: a y/N is answered without reading.

    ./argus delete-user --email person@example.com
    ./argus delete-user --email person@example.com --yes    # no prompt
"""
import argparse
import sys

from sqlalchemy import text

from app.database import SessionLocal, set_rls_context
from app.utils.security import mask_email


def plan(db, email: str) -> dict:
    """What deleting this account removes. Nothing is changed."""
    exists = db.execute(text("SELECT 1 FROM users WHERE email = :e"), {"e": email}).scalar()
    if not exists:
        return {}
    websites = db.execute(
        text("SELECT id, name FROM websites WHERE user_email = :e ORDER BY id"), {"e": email}
    ).all()
    ids = [w.id for w in websites] or [-1]
    pageviews = db.execute(
        text("SELECT count(*) FROM pageviews WHERE website_id = ANY(:ids)"), {"ids": ids}
    ).scalar()
    return {
        "websites": [f"{w.name} (#{w.id})" for w in websites],
        "pageviews": pageviews,
        "memberships": db.execute(
            text("SELECT count(*) FROM website_members WHERE user_email = :e"), {"e": email}
        ).scalar(),
        "sessions": db.execute(
            text("SELECT count(*) FROM sessions WHERE user_email = :e"), {"e": email}
        ).scalar(),
    }


def delete(db, email: str) -> dict:
    """Delete the account and what belongs to it, in one transaction."""
    what = plan(db, email)
    if not what:
        return {}
    db.execute(text("DELETE FROM website_members WHERE user_email = :e"), {"e": email})
    db.execute(text("DELETE FROM account_usage WHERE owner_email = :e"), {"e": email})
    # Sessions and owned websites, and everything under the websites, go with
    # the user through their ON DELETE CASCADE foreign keys.
    db.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})
    db.commit()
    return what


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Delete an account on request.")
    parser.add_argument("--email", required=True, help="the account to delete")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args(argv)
    email = args.email.strip().lower()

    db = SessionLocal()
    # Spans tenants by nature: the account, its websites, other people's teams.
    set_rls_context(db, context="job")
    try:
        what = plan(db, email)
        if not what:
            print(f"No account {email}.", file=sys.stderr)
            return 1

        print(f"Deleting {email} removes:")
        print(f"  websites it owns:   {len(what['websites'])}" + (
            "".join(f"\n    {w}" for w in what["websites"])))
        print(f"  their pageviews:    {what['pageviews']}, with all other recorded traffic")
        print(f"  team memberships:   {what['memberships']}")
        print(f"  sessions:           {what['sessions']}")
        print("This cannot be undone. The nightly backups still hold it until they rotate out.")

        if not args.yes:
            typed = input("Type the address again to delete it: ").strip().lower()
            if typed != email:
                print("Not the same address. Nothing deleted.", file=sys.stderr)
                return 1

        delete(db, email)
        print(f"Deleted {mask_email(email)}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
