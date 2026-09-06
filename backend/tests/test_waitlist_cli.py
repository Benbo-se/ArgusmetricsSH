"""Reading and managing the waiting list from the command line.

The signup page collects addresses. It was built without any way to read one,
which makes the collecting pointless, and without any way to delete one, which
made the sentence printed on that page ("deleted whenever you ask") a promise
with nothing behind it.

So `remove` is not a convenience command, it is the mechanism behind a
commitment made to a visitor, and it has the most tests here.
"""
import io
import uuid
from contextlib import redirect_stdout

import pytest
from sqlalchemy import text

from app import waitlist as cli


@pytest.fixture
def joined(db):
    """Two addresses on the list, cleaned up afterwards."""
    made = [f"cli-{uuid.uuid4().hex[:8]}@example.com" for _ in range(2)]
    for email in made:
        db.execute(
            text("SELECT argus_join_waitlist(:e, :s)"),
            {"e": email, "s": "/signup"},
        )
    db.commit()
    yield made
    for email in made:
        db.execute(text("DELETE FROM waitlist WHERE email = :e"), {"e": email})
    db.commit()


@pytest.fixture(autouse=True)
def same_session(db, monkeypatch):
    """The commands open their own session; point them at the test's.

    Without this they commit to the real database outside the transaction the
    test fixture rolls back, and a test that deletes rows would delete real
    ones.
    """
    monkeypatch.setattr(cli, "_session", lambda: db)
    # The commands close what they open. The fixture owns this session.
    monkeypatch.setattr(db, "close", lambda: None)
    return db


def _run(*argv) -> tuple:
    """Run a command, returning (exit code, stdout)."""
    out = io.StringIO()
    with redirect_stdout(out):
        code = cli.main(list(argv))
    return code, out.getvalue()


def _exists(db, email) -> bool:
    return bool(db.execute(
        text("SELECT count(*) FROM waitlist WHERE email = :e"), {"e": email}
    ).scalar())


class TestRemove:
    """The deletion promise on the signup page."""

    def test_it_deletes_the_address(self, db, joined):
        code, _ = _run("remove", joined[0])

        assert code == 0
        assert not _exists(db, joined[0])

    def test_it_leaves_everyone_else(self, db, joined):
        _run("remove", joined[0])
        assert _exists(db, joined[1])

    def test_it_does_not_care_about_case(self, db, joined):
        """Addresses are stored lower-cased. Somebody writing to ask for
        deletion will not necessarily match how they typed it."""
        code, _ = _run("remove", joined[0].upper())

        assert code == 0
        assert not _exists(db, joined[0])

    def test_an_unknown_address_says_so_and_fails(self, db):
        """"Done" for an address that was never there is the wrong answer to
        give somebody who wants to know their data is gone."""
        code, output = _run("remove", "never-joined@example.com")

        assert code != 0
        assert "not on the list" in output


class TestListing:
    def test_it_shows_who_is_waiting(self, db, joined):
        _, output = _run("list")
        assert joined[0] in output and joined[1] in output

    def test_notified_people_are_hidden_by_default(self, db, joined):
        _run("mark-notified", joined[0])
        _, output = _run("list")

        assert joined[0] not in output
        assert joined[1] in output

    def test_all_shows_them(self, db, joined):
        _run("mark-notified", joined[0])
        _, output = _run("list", "--all")
        assert joined[0] in output

    def test_count_separates_waiting_from_notified(self, db, joined):
        _run("mark-notified", joined[0])
        _, output = _run("count")
        assert "not yet notified" in output


class TestExport:
    def test_it_is_csv_with_a_header(self, db, joined):
        _, output = _run("export")
        lines = [l for l in output.splitlines() if l.strip()]

        assert lines[0] == "email,source,created_at,notified_at"
        assert any(joined[0] in line for line in lines[1:])

    def test_it_leaves_out_people_already_notified(self, db, joined):
        _run("mark-notified", joined[0])
        _, output = _run("export")

        assert joined[0] not in output
        assert joined[1] in output


class TestMarkNotified:
    def test_it_does_not_mark_the_same_person_twice(self, db, joined):
        """Run after the mail goes out, so the count says what was sent."""
        _run("mark-notified", joined[0])
        _, output = _run("mark-notified", joined[0])

        assert "Marked 0" in output

    def test_all_marks_everyone_waiting(self, db, joined):
        _, output = _run("mark-notified", "--all")
        assert "Marked 2" in output

    def test_it_needs_an_address_or_all(self, db):
        """Otherwise a typo silently marks nobody and reads as success."""
        with pytest.raises(SystemExit):
            _run("mark-notified")
