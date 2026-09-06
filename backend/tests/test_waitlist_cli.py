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
import sys
from contextlib import redirect_stdout
from unittest.mock import patch

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


def _run(*argv, answer=None) -> tuple:
    """Run a command, returning (exit code, stdout).

    `answer` is fed to the prompt. `remove` asks which entry rather than
    taking an address, because an address on the command line is one that can
    be pasted from an example, and one was: a placeholder went into a live
    instance's configuration verbatim because it looked real.
    """
    out = io.StringIO()
    stdin = io.StringIO(answer if answer is not None else "")
    # sys.stdin directly: contextlib has redirect_stdout and redirect_stderr
    # and no redirect_stdin, and input() reads sys.stdin.
    with redirect_stdout(out), patch.object(sys, "stdin", stdin):
        code = cli.main(list(argv))
    return code, out.getvalue()


def _exists(db, email) -> bool:
    return bool(db.execute(
        text("SELECT count(*) FROM waitlist WHERE email = :e"), {"e": email}
    ).scalar())


class TestRemove:
    """The deletion promise on the signup page, and the shape that keeps it
    from deleting the wrong person."""

    def test_it_takes_no_address_argument(self):
        """The whole point. An argument can be pasted from an example."""
        import inspect

        source = inspect.getsource(cli.main)
        remove_block = source.split('"remove"')[1].split('"mark-notified"')[0]
        assert "add_argument" not in remove_block, (
            "remove takes an argument again, so an address from an example "
            "can be handed to it"
        )

    def test_it_deletes_the_one_chosen(self, db, joined):
        code, output = _run("remove", answer="1\n")

        assert code == 0, output
        assert not _exists(db, joined[0])
        assert _exists(db, joined[1]), "it removed more than the one chosen"

    def test_it_lists_them_so_there_is_nothing_to_type(self, db, joined):
        _, output = _run("remove", answer="2\n")

        assert joined[0] in output and joined[1] in output

    def test_a_number_nobody_offered_is_refused(self, db, joined):
        code, output = _run("remove", answer="99\n")

        assert code != 0
        assert _exists(db, joined[0]) and _exists(db, joined[1])
        assert "Give the number" in output

    def test_something_that_is_not_a_number_is_refused(self, db, joined):
        code, _ = _run("remove", answer="anna\n")

        assert code != 0
        assert _exists(db, joined[0])

    def test_walking_away_removes_nobody(self, db, joined):
        """No answer at all, which is what closing the terminal looks like."""
        code, _ = _run("remove", answer="")

        assert code != 0
        assert _exists(db, joined[0]) and _exists(db, joined[1])

    def test_an_empty_list_says_so(self, db):
        db.execute(text("DELETE FROM waitlist"))
        db.commit()

        code, output = _run("remove", answer="1\n")

        assert code != 0
        assert "empty" in output


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
