"""The instance-wide admin page, and who cannot see it.

This is the first thing in the product that is not scoped to one website, so
it is the first place a mistake means one account seeing another's data. Most
of what follows is about the door rather than the room.

Who may open it comes from configuration, not from a column on users. An
attacker who reaches the database cannot write themselves an administrator,
and a real role model with permissions and deprovisioning belongs in one piece
rather than half-built here.

It answers 404 rather than 403. A 403 tells an account that the page exists
and that it is simply not allowed in, which on an instance whose administrator
is one named person is a fact worth not handing out.
"""
import uuid

import pytest
from sqlalchemy import text

from app.config import settings


@pytest.fixture
def as_admin(monkeypatch, website):
    """The fixture account, made an administrator through configuration."""
    monkeypatch.setattr(settings, "ADMIN_EMAILS", website["email"])
    return website["email"]


@pytest.fixture
def waiting(db):
    address = f"waiting-{uuid.uuid4().hex[:8]}@example.com"
    db.execute(
        text("SELECT argus_join_waitlist(:e, :s)"),
        {"e": address, "s": "/signup"},
    )
    db.commit()
    yield address
    db.execute(text("DELETE FROM waitlist WHERE email = :e"), {"e": address})
    db.commit()


class TestWhoCanOpenIt:
    def test_an_administrator_can(self, owner_client, as_admin):
        response = owner_client.get("/dashboard/admin")

        assert response.status_code == 200
        assert "Instance admin" in response.text

    def test_an_ordinary_account_gets_a_404(self, owner_client, monkeypatch):
        """Not a 403. The page does not confirm it exists."""
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "someone-else@example.com")

        response = owner_client.get("/dashboard/admin")

        assert response.status_code == 404, (
            f"answered {response.status_code}; a 403 tells the account the "
            "page is there and that it is the account that is the problem"
        )
        assert "Instance admin" not in response.text

    def test_nobody_can_when_the_setting_is_empty(self, owner_client, monkeypatch):
        """An instance that never configured this should get no admin page,
        rather than one where the first account to exist is in charge."""
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "")

        assert owner_client.get("/dashboard/admin").status_code == 404

    def test_signing_in_is_still_required(self, client, monkeypatch):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "anyone@example.com")

        response = client.get("/dashboard/admin", follow_redirects=False)

        assert response.status_code in (302, 307, 401, 403, 404)
        assert "Instance admin" not in response.text

    def test_the_address_is_matched_whole(self, owner_client, monkeypatch, website):
        """A substring check would make eda@example.com an administrator on an
        instance configured for reda@example.com."""
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "x" + website["email"])

        assert owner_client.get("/dashboard/admin").status_code == 404

    def test_case_does_not_matter(self, owner_client, monkeypatch, website):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", website["email"].upper())
        assert owner_client.get("/dashboard/admin").status_code == 200

    def test_several_addresses_can_be_listed(self, owner_client, monkeypatch, website):
        monkeypatch.setattr(
            settings, "ADMIN_EMAILS", f"first@example.com, {website['email']} "
        )
        assert owner_client.get("/dashboard/admin").status_code == 200


class TestWhatItShows:
    def test_the_waiting_list_is_there(self, owner_client, as_admin, waiting):
        assert waiting in owner_client.get("/dashboard/admin").text

    def test_an_empty_list_says_so(self, owner_client, as_admin, db):
        db.execute(text("DELETE FROM waitlist"))
        db.commit()

        assert "Nobody has joined" in owner_client.get("/dashboard/admin").text

    def test_it_is_not_linked_from_the_rest_of_the_dashboard(self):
        """Deliberate: it is reachable by typing the path, and by nothing
        else, so an account that cannot open it is never shown a door."""
        import pathlib

        sidebar = (
            pathlib.Path(__file__).resolve().parents[1]
            / "app" / "templates" / "components" / "sidebar.html"
        ).read_text()
        assert "/dashboard/admin" not in sidebar


class TestRemoving:
    def test_an_administrator_can_remove_an_address(
        self, owner_client, as_admin, waiting, db
    ):
        """The mechanism behind "deleted whenever you ask" on the signup page."""
        response = owner_client.post(
            "/dashboard/admin/waitlist/remove",
            data={"email": waiting},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert db.execute(
            text("SELECT count(*) FROM waitlist WHERE email = :e"), {"e": waiting}
        ).scalar() == 0

    def test_an_ordinary_account_cannot(self, owner_client, monkeypatch, waiting, db):
        monkeypatch.setattr(settings, "ADMIN_EMAILS", "someone-else@example.com")

        response = owner_client.post(
            "/dashboard/admin/waitlist/remove", data={"email": waiting}
        )

        assert response.status_code == 404
        assert db.execute(
            text("SELECT count(*) FROM waitlist WHERE email = :e"), {"e": waiting}
        ).scalar() == 1, "a non-administrator deleted a row"

    def test_it_is_not_a_get(self, owner_client, as_admin, waiting, db):
        """A GET that deletes is reachable from a link and from anything that
        prefetches, which is why logging out is a form here too."""
        response = owner_client.get(
            f"/dashboard/admin/waitlist/remove?email={waiting}"
        )

        assert response.status_code in (404, 405)
        assert db.execute(
            text("SELECT count(*) FROM waitlist WHERE email = :e"), {"e": waiting}
        ).scalar() == 1
