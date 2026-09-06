"""Read and manage the list of people waiting for hosted signup.

    python -m app.waitlist count
    python -m app.waitlist list
    python -m app.waitlist export > waitlist.csv
    python -m app.waitlist remove someone@example.com
    python -m app.waitlist mark-notified --all

The signup page collects addresses. Without this there was no way to see one,
which makes the collecting pointless, and no way to delete one, which makes
the sentence on that page ("deleted whenever you ask") a promise with nothing
behind it. `remove` is how that promise is kept, so it is not a convenience.

`mark-notified` exists so a second announcement does not reach the same people
twice. Run it after the mail goes out, not before: a crash between the two
would rather leave someone un-notified than tell them the same thing again.
"""
import argparse
import csv
import sys


def say(message: str) -> None:
    """Results go to stdout, so `export` pipes and `list` can be grepped.

    Not the logger: this is a command's answer, not a diagnostic, and a
    logger writes to stderr where a pipe will not see it.
    """
    print(message)


def _session():
    from app.database import SessionLocal, set_rls_context

    session = SessionLocal()
    # The job context is the one the table's policies grant writes to. Naming
    # it here rather than relying on being the table owner keeps this working
    # the same way in production, where the app is not the owner.
    set_rls_context(session, context="job")
    return session


def _rows(session, where: str = "", params: dict = None):
    from sqlalchemy import text

    return session.execute(
        text(
            "SELECT email, source, created_at, notified_at "
            f"  FROM waitlist {where} ORDER BY created_at"
        ),
        params or {},
    ).all()


def _count(args) -> int:
    from sqlalchemy import text

    session = _session()
    try:
        total, waiting = session.execute(
            text(
                "SELECT count(*), count(*) FILTER (WHERE notified_at IS NULL) "
                "  FROM waitlist"
            )
        ).one()
    finally:
        session.close()

    say(f"{total} on the list, {waiting} not yet notified")
    return 0


def _list(args) -> int:
    session = _session()
    try:
        rows = _rows(session, "" if args.all else "WHERE notified_at IS NULL")
    finally:
        session.close()

    if not rows:
        say("Nobody is waiting." if not args.all else "The list is empty.")
        return 0

    for email, source, created, notified in rows:
        state = "notified" if notified else "waiting"
        say(
            f"{created:%Y-%m-%d %H:%M}  {state:<8}  {source or '-':<20}  {email}"
        )
    say(f"{len(rows)} entries")
    return 0


def _export(args) -> int:
    """CSV on stdout, so it pipes into whatever sends the mail."""
    session = _session()
    try:
        rows = _rows(session, "" if args.all else "WHERE notified_at IS NULL")
    finally:
        session.close()

    writer = csv.writer(sys.stdout)
    writer.writerow(["email", "source", "created_at", "notified_at"])
    for email, source, created, notified in rows:
        writer.writerow([email, source or "", created.isoformat(),
                         notified.isoformat() if notified else ""])
    return 0


def _remove(args) -> int:
    """Delete one address, because somebody asked.

    Says plainly whether it found anything. "Done" for an address that was
    never there would be the wrong answer to give someone who wants to know
    their data is gone.
    """
    from sqlalchemy import text

    email = args.email.strip().lower()
    session = _session()
    try:
        removed = session.execute(
            text("DELETE FROM waitlist WHERE email = :e RETURNING email"),
            {"e": email},
        ).rowcount
        session.commit()
    finally:
        session.close()

    if removed:
        say(f"Removed {email}")
        return 0
    say(f"{email} is not on the list; nothing to remove")
    return 1


def _mark_notified(args) -> int:
    from sqlalchemy import text

    session = _session()
    try:
        if args.all:
            updated = session.execute(
                text("UPDATE waitlist SET notified_at = now() "
                     " WHERE notified_at IS NULL")
            ).rowcount
        else:
            updated = session.execute(
                text("UPDATE waitlist SET notified_at = now() "
                     " WHERE email = :e AND notified_at IS NULL"),
                {"e": args.email.strip().lower()},
            ).rowcount
        session.commit()
    finally:
        session.close()

    say(f"Marked {updated} as notified")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.waitlist", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    count = sub.add_parser("count", help="how many are waiting")
    count.set_defaults(func=_count)

    listing = sub.add_parser("list", help="who is waiting")
    listing.add_argument("--all", action="store_true",
                         help="include people already notified")
    listing.set_defaults(func=_list)

    export = sub.add_parser("export", help="CSV on stdout")
    export.add_argument("--all", action="store_true",
                        help="include people already notified")
    export.set_defaults(func=_export)

    remove = sub.add_parser(
        "remove", help="delete one address (a deletion request)")
    remove.add_argument("email")
    remove.set_defaults(func=_remove)

    notified = sub.add_parser(
        "mark-notified", help="record that the announcement has been sent")
    notified.add_argument("email", nargs="?", default=None)
    notified.add_argument("--all", action="store_true")
    notified.set_defaults(func=_mark_notified)

    args = parser.parse_args(argv)
    if args.command == "mark-notified" and not args.all and not args.email:
        parser.error("give an address, or --all")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
