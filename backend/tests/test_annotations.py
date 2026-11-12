"""Notes on the traffic graph (#220).

What is checked here is what the application decides: who may write, which
website a note id belongs to, what text is accepted, which notes a range
shows, and that somebody's typing stays text on every page it reaches.

The development database connects as the table owner, where row-level
security never applies, so nothing here proves a policy. Those tests are in
test_tenant_isolation.py (TestAnnotations), which runs as an unprivileged
role.
"""
import csv
import io
import json
import re
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from app.main import app
from app.models.annotation import MAX_NOTE_LENGTH
from app.schemas.annotation import clean_note
from app.services import annotations_service
from app.services.analytics_service import AnalyticsService
from app.utils.date_helpers import resolve_range
from tests.conftest import count, reason

STOCKHOLM = "Europe/Stockholm"
API = "/api/v1/annotations"


def _note(db, website_id, day, note="A note"):
    note_id = db.execute(
        text(
            "INSERT INTO annotations (website_id, day, note) "
            "VALUES (:w, :d, :n) RETURNING id"
        ),
        {"w": website_id, "d": day, "n": note},
    ).scalar()
    db.commit()
    return note_id


def _stored(db, note_id):
    return db.execute(
        text("SELECT website_id, day, note FROM annotations WHERE id = :i"), {"i": note_id}
    ).one_or_none()


def _member(db, website, role):
    """Another account, an active member of the fixture website."""
    email = f"{role}-{uuid.uuid4().hex[:8]}@example.com"
    db.execute(
        text("INSERT INTO users (email, is_verified, created_at) VALUES (:e, true, now())"),
        {"e": email},
    )
    db.execute(
        text(
            "INSERT INTO website_members (website_id, user_email, owner_email, role,"
            "  status, invited_by, invited_at) "
            "VALUES (:w, :u, :o, :r, 'active', :o, now())"
        ),
        {"w": website["id"], "u": email, "o": website["email"], "r": role},
    )
    db.commit()
    return email


def _stranger(db):
    email = f"stranger-{uuid.uuid4().hex[:8]}@example.com"
    db.execute(
        text("INSERT INTO users (email, is_verified, created_at) VALUES (:e, true, now())"),
        {"e": email},
    )
    db.commit()
    return email


@contextmanager
def acting_as(db, email):
    """Requests made inside are this account's, the way owner_client's are
    the owner's."""
    from app.database import set_rls_context
    from app.models.user import User
    from app.routers.auth import get_current_user

    user = db.query(User).filter(User.email == email).first()
    assert user is not None, f"no user {email}; the test would be testing a 401"

    def _as_user():
        set_rls_context(db, context="user", user_email=user.email)
        return user

    before = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = _as_user
    try:
        yield
    finally:
        if before is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = before


def _page_notes(body):
    """The notes the dashboard page handed to the graph."""
    island = re.search(
        r'<script type="application/json" id="chart-notes-data">(.*?)</script>', body, re.S
    )
    assert island, "the page has no notes island; nothing below is being tested"
    return json.loads(island.group(1))


# --- writing -----------------------------------------------------------------


class TestWriting:
    def test_the_owner_adds_a_note_and_it_is_stored(self, owner_client, db, website):
        r = owner_client.post(
            f"{API}?website_id={website['id']}",
            json={"day": "2026-03-04", "note": "New start page"},
        )
        assert r.status_code == 201, r.text
        row = _stored(db, r.json()["id"])
        assert row is not None, "201, and no row"
        assert (row.website_id, row.day, row.note) == (
            website["id"], date(2026, 3, 4), "New start page",
        )

    def test_a_note_is_changed(self, owner_client, db, website):
        note_id = _note(db, website["id"], "2026-03-04", "Before")
        r = owner_client.put(
            f"{API}/{note_id}?website_id={website['id']}",
            json={"day": "2026-03-05", "note": "After"},
        )
        assert r.status_code == 200, r.text
        row = _stored(db, note_id)
        assert (row.day, row.note) == (date(2026, 3, 5), "After")

    def test_a_note_is_deleted(self, owner_client, db, website):
        note_id = _note(db, website["id"], "2026-03-04")
        r = owner_client.delete(f"{API}/{note_id}?website_id={website['id']}")
        assert r.status_code == 200, r.text
        assert _stored(db, note_id) is None, "the note is still there"

    def test_the_list_is_the_websites_notes_in_day_order(self, owner_client, db, website):
        _note(db, website["id"], "2026-03-09", "third")
        _note(db, website["id"], "2026-03-01", "first")
        _note(db, website["id"], "2026-03-05", "second")
        r = owner_client.get(f"{API}?website_id={website['id']}")
        assert r.status_code == 200, r.text
        assert [n["note"] for n in r.json()] == ["first", "second", "third"]

        bounded = owner_client.get(
            f"{API}?website_id={website['id']}&start_date=2026-03-02&end_date=2026-03-05"
        )
        assert [n["note"] for n in bounded.json()] == ["second"]

    def test_without_a_session_nothing_is_written(self, client, db, website):
        r = client.post(
            f"{API}?website_id={website['id']}",
            json={"day": "2026-03-04", "note": "x"},
        )
        assert r.status_code == 401, r.text
        assert count(db, "annotations", website_id=website["id"]) == 0


class TestTheText:
    def test_whitespace_and_control_characters_become_one_line(self):
        assert clean_note("  a\tb\n\nc \x00 d e  ") == "a b c d e"

    def test_a_note_is_stored_cleaned(self, owner_client, db, website):
        r = owner_client.post(
            f"{API}?website_id={website['id']}",
            json={"day": "2026-03-04", "note": "  Campaign\n started\t "},
        )
        assert r.status_code == 201, r.text
        assert _stored(db, r.json()["id"]).note == "Campaign started"

    def test_the_longest_note_is_accepted_and_one_more_character_is_not(
        self, owner_client, db, website
    ):
        url = f"{API}?website_id={website['id']}"
        fits = owner_client.post(url, json={"day": "2026-03-04", "note": "x" * MAX_NOTE_LENGTH})
        assert fits.status_code == 201, fits.text

        too_long = owner_client.post(
            url, json={"day": "2026-03-04", "note": "x" * (MAX_NOTE_LENGTH + 1)}
        )
        assert too_long.status_code == 422, too_long.text
        assert "at most" in json.dumps(too_long.json()), too_long.text
        assert count(db, "annotations", website_id=website["id"]) == 1

    def test_changing_a_note_has_the_same_limit(self, owner_client, db, website):
        note_id = _note(db, website["id"], "2026-03-04", "short")
        r = owner_client.put(
            f"{API}/{note_id}?website_id={website['id']}",
            json={"day": "2026-03-04", "note": "x" * (MAX_NOTE_LENGTH + 1)},
        )
        assert r.status_code == 422, r.text
        assert _stored(db, note_id).note == "short"

    @pytest.mark.parametrize("note", ["", "   ", "\n\t"])
    def test_an_empty_note_is_refused(self, owner_client, db, website, note):
        r = owner_client.post(
            f"{API}?website_id={website['id']}", json={"day": "2026-03-04", "note": note}
        )
        assert r.status_code == 422, r.text
        assert "needs some text" in json.dumps(r.json()), r.text
        assert count(db, "annotations", website_id=website["id"]) == 0

    @pytest.mark.parametrize("day", ["yesterday", "2026-02-30", "1850-01-01", "2026-03-04T10:00:00"])
    def test_a_day_that_is_not_a_day_is_refused(self, owner_client, db, website, day):
        r = owner_client.post(
            f"{API}?website_id={website['id']}", json={"day": day, "note": "x"}
        )
        assert r.status_code == 422, r.text
        assert count(db, "annotations", website_id=website["id"]) == 0

    def test_a_website_holds_a_limited_number_of_notes(
        self, owner_client, db, website, monkeypatch
    ):
        monkeypatch.setattr(annotations_service, "MAX_PER_WEBSITE", 2)
        url = f"{API}?website_id={website['id']}"
        for n in range(2):
            assert owner_client.post(
                url, json={"day": "2026-03-04", "note": f"note {n}"}
            ).status_code == 201
        full = owner_client.post(url, json={"day": "2026-03-04", "note": "one too many"})
        assert full.status_code == 400, full.text
        assert "notes" in reason(full)
        assert count(db, "annotations", website_id=website["id"]) == 2


# --- who may ------------------------------------------------------------------


class TestRoles:
    """Everyone on the team reads; owner and admin write. As for goals."""

    def test_a_viewer_reads_and_cannot_write(self, client, db, website):
        note_id = _note(db, website["id"], "2026-03-04", "Owner's note")
        viewer = _member(db, website, "viewer")
        with acting_as(db, viewer):
            listed = client.get(f"{API}?website_id={website['id']}")
            assert listed.status_code == 200, listed.text
            assert [n["note"] for n in listed.json()] == ["Owner's note"]

            url = f"{API}?website_id={website['id']}"
            one = f"{API}/{note_id}?website_id={website['id']}"
            created = client.post(url, json={"day": "2026-03-05", "note": "viewer"})
            changed = client.put(one, json={"day": "2026-03-05", "note": "viewer"})
            deleted = client.delete(one)

        for response in (created, changed, deleted):
            assert response.status_code == 403, response.text
            assert "admin access" in reason(response)
        assert count(db, "annotations", website_id=website["id"]) == 1
        assert _stored(db, note_id).note == "Owner's note"

    def test_an_admin_writes(self, client, db, website):
        admin = _member(db, website, "admin")
        with acting_as(db, admin):
            url = f"{API}?website_id={website['id']}"
            created = client.post(url, json={"day": "2026-03-05", "note": "by admin"})
            assert created.status_code == 201, created.text
            one = f"{API}/{created.json()['id']}?website_id={website['id']}"
            assert client.put(one, json={"day": "2026-03-06", "note": "changed"}).status_code == 200
            assert client.delete(one).status_code == 200
        assert count(db, "annotations", website_id=website["id"]) == 0

    def test_someone_else_reads_and_writes_nothing(self, client, db, website):
        note_id = _note(db, website["id"], "2026-03-04", "Private")
        with acting_as(db, _stranger(db)):
            url = f"{API}?website_id={website['id']}"
            one = f"{API}/{note_id}?website_id={website['id']}"
            responses = [
                client.get(url),
                client.post(url, json={"day": "2026-03-05", "note": "x"}),
                client.put(one, json={"day": "2026-03-05", "note": "x"}),
                client.delete(one),
            ]
        for response in responses:
            # 404, not 403: a stranger is not told the website exists.
            assert response.status_code == 404, response.text
            assert "website not found" in reason(response)
            assert "Private" not in response.text
        assert _stored(db, note_id).note == "Private"

    def test_a_note_id_from_another_website_finds_nothing(
        self, owner_client, db, website, second_website
    ):
        """Both websites are the caller's own, so the role check passes for
        either. The note still has to be on the website named in the request:
        otherwise an admin of one website could change the notes of any
        other by counting ids."""
        note_id = _note(db, second_website["id"], "2026-03-04", "On the second site")
        one = f"{API}/{note_id}?website_id={website['id']}"

        changed = owner_client.put(one, json={"day": "2026-03-05", "note": "moved"})
        deleted = owner_client.delete(one)

        for response in (changed, deleted):
            assert response.status_code == 404, response.text
            assert "note not found" in reason(response)
        row = _stored(db, note_id)
        assert row is not None, "the note was deleted through another website"
        assert (row.website_id, row.note) == (second_website["id"], "On the second site")


# --- which notes a range shows --------------------------------------------------


def _at(*args):
    return datetime(*args, tzinfo=timezone.utc)


class TestTheDayIsTheWebsitesDay:
    def test_today_is_today_in_the_websites_zone(self, db, website):
        """23:30 UTC on the 12th is already the 13th in Stockholm."""
        _note(db, website["id"], "2026-11-12", "the 12th")
        _note(db, website["id"], "2026-11-13", "the 13th")
        now = _at(2026, 11, 12, 23, 30)

        in_utc = annotations_service.annotations_in_window(
            db, website["id"], resolve_range("today", "UTC", now=now)
        )
        in_stockholm = annotations_service.annotations_in_window(
            db, website["id"], resolve_range("today", STOCKHOLM, now=now)
        )

        assert [n["note"] for n in in_utc] == ["the 12th"]
        assert [n["note"] for n in in_stockholm] == ["the 13th"]

    @pytest.mark.parametrize("key,expected_bucket", [("7d", "day"), ("yesterday", "hour")])
    def test_the_days_listed_are_the_days_the_graph_has_points_for(
        self, db, website, key, expected_bucket
    ):
        """The graph puts a note on the first point whose date starts with
        the note's day (annotationsByPoint in dashboard.js). So the first ten
        characters of every point's date have to be a day in the website's
        zone, by the day and by the hour, and the range the notes are read
        for has to be the range of those days."""
        window = resolve_range(key, STOCKHOLM)
        assert window.bucket == expected_bucket
        stats = AnalyticsService(db).get_dashboard_stats(
            website_id=website["id"], start_date=window.start, end_date=window.end,
            compare=False, tz=STOCKHOLM, bucket=window.bucket,
        )
        point_days = [str(p["date"])[:10] for p in stats["timeseries"]]
        assert point_days, "no points; nothing compared"
        for day in point_days:
            date.fromisoformat(day)

        first_day, last_day = annotations_service.window_days(window)
        assert (point_days[0], point_days[-1]) == (first_day.isoformat(), last_day.isoformat())


class TestTheDashboardPage:
    RANGE = "range=custom&start_date=2026-03-01&end_date=2026-03-10"

    def test_it_carries_the_notes_of_the_range_and_no_others(self, owner_client, db, website):
        _note(db, website["id"], "2026-02-28", "day before")
        first = _note(db, website["id"], "2026-03-01", "first day")
        last = _note(db, website["id"], "2026-03-10", "last day")
        _note(db, website["id"], "2026-03-11", "day after")

        r = owner_client.get(f"/dashboard/website/{website['id']}?{self.RANGE}")
        assert r.status_code == 200, r.text[:300]
        data = _page_notes(r.text)

        assert data["notes"] == [
            {"id": first, "day": "2026-03-01", "note": "first day"},
            {"id": last, "day": "2026-03-10", "note": "last day"},
        ]
        assert (data["first_day"], data["last_day"]) == ("2026-03-01", "2026-03-10")
        assert data["website_id"] == website["id"]

    def test_another_websites_notes_are_not_on_it(
        self, owner_client, db, website, second_website
    ):
        _note(db, second_website["id"], "2026-03-04", "other site")
        r = owner_client.get(f"/dashboard/website/{website['id']}?{self.RANGE}")
        assert _page_notes(r.text)["notes"] == []

    def test_the_owner_gets_the_form_and_a_viewer_does_not(self, owner_client, client, db, website):
        _note(db, website["id"], "2026-03-04", "seen by all")
        as_owner = owner_client.get(f"/dashboard/website/{website['id']}?{self.RANGE}").text
        assert 'id="note-text"' in as_owner and "rowAskDelete" in as_owner

        with acting_as(db, _member(db, website, "viewer")):
            as_viewer = client.get(f"/dashboard/website/{website['id']}?{self.RANGE}")
        assert as_viewer.status_code == 200, as_viewer.text[:300]
        assert [n["note"] for n in _page_notes(as_viewer.text)["notes"]] == ["seen by all"]
        for control in ('id="note-text"', "rowAskDelete", "rowEdit", "openNoteForm"):
            assert control not in as_viewer.text, f"a viewer is offered {control}"

    @pytest.mark.parametrize("payload", [
        "</script><script>alert(1)</script>",
        '"><img src=x onerror=alert(1)>',
        "<svg/onload=alert(1)>",
        "'; alert(1); //",
    ])
    def test_hostile_text_stays_text(self, owner_client, db, website, payload):
        """The note is typed by an admin and read by the whole team. On the
        page it exists once, inside the JSON island, where it must not be
        able to end the script element or form a tag."""
        created = owner_client.post(
            f"{API}?website_id={website['id']}", json={"day": "2026-03-04", "note": payload}
        )
        assert created.status_code == 201, created.text

        body = owner_client.get(f"/dashboard/website/{website['id']}?{self.RANGE}").text

        assert [n["note"] for n in _page_notes(body)["notes"]] == [payload], (
            "the note did not survive the trip, so its absence below proves nothing"
        )
        for live in ("<script>alert(1)", "<img src=x", "<svg/onload", '"><img'):
            assert live not in body, f"{live!r} is live markup on the page"
        # And nowhere but the island: not in an attribute, not in the markup.
        island = re.search(r'id="chart-notes-data">(.*?)</script>', body, re.S).group(0)
        assert "alert(1)" not in body.replace(island, ""), "the note is on the page outside the island"


class TestThePublicLink:
    def test_notes_are_not_on_the_shared_dashboard(self, client, db, shared_website):
        """A note is the team's working note. Somebody holding the link sees
        the numbers, not what the team wrote about them."""
        _note(db, shared_website["id"], datetime.now(timezone.utc).date().isoformat(),
              "Fired the agency")
        r = client.get(f"/public/{shared_website['share_token']}")
        assert r.status_code == 200, r.text[:300]
        assert 'id="pageviews-chart"' in r.text, "not the dashboard; nothing below is tested"
        assert "Fired the agency" not in r.text
        assert "chart-notes-data" not in r.text


class TestExportAndDeletion:
    def test_the_csv_export_has_the_notes_of_its_range(self, owner_client, db, website):
        _note(db, website["id"], "2026-03-04", "Campaign started")
        _note(db, website["id"], "2026-03-05", "=HYPERLINK(\"http://x\")")
        _note(db, website["id"], "2026-04-01", "outside")

        r = owner_client.get(
            f"/dashboard/website/{website['id']}/export-csv"
            "?range=custom&start_date=2026-03-01&end_date=2026-03-10"
        )
        assert r.status_code == 200, r.text[:300]
        rows = list(csv.reader(io.StringIO(r.text)))
        start = rows.index(["NOTES"])
        assert rows[start + 1] == ["Date", "Note"]
        assert rows[start + 2] == ["2026-03-04", "Campaign started"]
        # A formula would run in whoever's spreadsheet opens the file.
        assert rows[start + 3] == ["2026-03-05", "'=HYPERLINK(\"http://x\")"]
        assert rows[start + 4] == []
        assert "outside" not in r.text

    def test_an_export_without_notes_has_no_notes_section(self, owner_client, db, website):
        r = owner_client.get(f"/dashboard/website/{website['id']}/export-csv?range=7d")
        assert r.status_code == 200
        assert ["NOTES"] not in list(csv.reader(io.StringIO(r.text)))

    def test_deleting_the_account_deletes_its_notes(self, db, website):
        from app import delete_user

        note_id = _note(db, website["id"], "2026-03-04", "goes with the account")
        assert delete_user.delete(db, website["email"]), "nothing was deleted"
        assert _stored(db, note_id) is None, "the note outlived its website"
