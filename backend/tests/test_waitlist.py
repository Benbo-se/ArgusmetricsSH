"""The page "Get started free" leads to while hosted signup is closed.

It used to lead to a redirect back to /login, so the button appeared to do
nothing: the page did not change and nothing said why. That is the same shape
of failure as a countries panel saying "no data yet" when no country database
exists. The interface promised something the server had already decided not to
do, and only the server knew.

The page asks for an address instead, which means storing one, which means an
endpoint that anyone on the internet can call. So most of what follows is
about what that endpoint refuses to do: it cannot read the list back, it
cannot be used to find out whether an address is on it, and it cannot be used
to fill the table.
"""
import uuid

import pytest
from sqlalchemy import text

from app.config import settings


@pytest.fixture
def closed(monkeypatch):
    """Registration closed, which is how argusmetrics.io actually runs."""
    monkeypatch.setattr(settings, "ENABLE_REGISTRATION", False)


@pytest.fixture(autouse=True)
def fresh_limits():
    """The rate limiter is process-global, so it leaks between tests.

    Without this, whichever test happens to run fifth gets a 429 and fails for
    a reason that has nothing to do with what it is checking. The limiting
    itself is still tested, deliberately, at the bottom of this file.
    """
    from app.middleware.rate_limit import rate_limiter

    rate_limiter.reset()
    yield
    rate_limiter.reset()


@pytest.fixture
def address():
    return f"waitlist-{uuid.uuid4().hex[:10]}@example.com"


def _rows(db, email):
    return db.execute(
        text("SELECT count(*) FROM waitlist WHERE email = :e"), {"e": email}
    ).scalar()


class TestTheSignupPage:
    def test_it_explains_itself_instead_of_redirecting(self, client, closed):
        """The bug as reported: clicking Create account did nothing."""
        response = client.get("/signup", follow_redirects=False)

        assert response.status_code == 200, (
            f"/signup answered {response.status_code}; a redirect here is what "
            "made the button look broken"
        )
        assert "Hosted signup is not open yet" in response.text

    def test_it_says_what_can_be_done_today(self, client, closed):
        """A page that only says no is a worse version of the redirect."""
        assert "github.com/Benbo-se/ArgusmetricsSH" in client.get("/signup").text

    def test_it_does_not_promise_a_date(self, client, closed):
        """"Coming soon" is a claim that goes stale on its own, which is the
        class of thing this codebase keeps having to correct."""
        text_ = client.get("/signup").text
        for phrase in ("coming soon", "next month", "later this year", "shortly"):
            assert phrase not in text_.lower(), f"the page promises {phrase!r}"

    def test_the_real_form_comes_back_when_registration_opens(self, client, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", True)
        response = client.get("/signup")

        assert response.status_code == 200
        assert "Create your account" in response.text

    def test_the_login_page_stops_offering_an_account(self, client, closed):
        """It linked to "No account? Create one", which redirected back to it."""
        response = client.get("/login")

        assert "No account? Create one" not in response.text
        assert "Hosted signup is not open yet" in response.text

    def test_the_login_page_offers_one_when_it_can(self, client, monkeypatch):
        monkeypatch.setattr(settings, "ENABLE_REGISTRATION", True)
        assert "No account? Create one" in client.get("/login").text


class TestJoining:
    def test_an_address_is_recorded(self, client, db, address):
        response = client.post("/api/v1/waitlist", json={"email": address})

        assert response.status_code == 200
        assert _rows(db, address) == 1

    def test_the_address_is_lower_cased(self, client, db, address):
        client.post("/api/v1/waitlist", json={"email": address.upper()})
        assert _rows(db, address) == 1

    def test_joining_twice_is_one_row(self, client, db, address):
        client.post("/api/v1/waitlist", json={"email": address})
        second = client.post("/api/v1/waitlist", json={"email": address})

        assert second.status_code == 200
        assert _rows(db, address) == 1

    def test_the_answer_is_the_same_either_way(self, client, address):
        """Otherwise the page tells anyone whether a given address is on the
        list, which is a thing this product does not disclose about people."""
        first = client.post("/api/v1/waitlist", json={"email": address})
        second = client.post("/api/v1/waitlist", json={"email": address})

        assert first.status_code == second.status_code
        assert first.json() == second.json()

    def test_a_malformed_address_is_refused(self, client):
        assert client.post(
            "/api/v1/waitlist", json={"email": "not-an-address"}
        ).status_code == 422

    def test_the_honeypot_is_accepted_and_discarded(self, client, db, address):
        """Told it worked, so it goes away, and nothing is written.

        A bot that is told it failed tries something else.
        """
        response = client.post(
            "/api/v1/waitlist", json={"email": address, "website": "http://spam"}
        )

        assert response.status_code == 200
        assert _rows(db, address) == 0

    def test_the_source_is_kept_short(self, client, db, address):
        client.post(
            "/api/v1/waitlist",
            json={"email": address, "source": "/" + "x" * 300},
        )
        stored = db.execute(
            text("SELECT source FROM waitlist WHERE email = :e"), {"e": address}
        ).scalar()
        assert stored is None or len(stored) <= 64


class TestWhatTheEndpointWillNotDo:
    """It is public. Everything it can do, anyone can do."""

    def test_it_never_returns_the_list(self, client, db, address):
        client.post("/api/v1/waitlist", json={"email": address})
        body = client.post("/api/v1/waitlist", json={"email": address}).json()

        assert address not in str(body)
        assert set(body) == {"message"}

    def test_there_is_no_way_to_read_it_over_http(self, client):
        """A GET on the same path must not have quietly become a listing."""
        assert client.get("/api/v1/waitlist").status_code in (404, 405)

    def test_it_stores_nothing_about_the_visitor(self, client, db, address):
        """An address is what was asked for. An address is what is kept.

        The columns are checked rather than the code, because the failure this
        guards against is a later migration adding ip_address to a table
        inside a product whose argument is that it keeps no visitor log.
        """
        columns = set(db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            " WHERE table_name = 'waitlist'"
        )).scalars().all())

        assert columns == {"id", "email", "source", "created_at", "notified_at"}, (
            f"the waitlist table has grown columns: {sorted(columns)}"
        )

    def test_the_write_goes_through_the_definer_function(self):
        """Not a policy. The caller is unauthenticated, and the way to let it
        do one thing is to write that thing down rather than to hand it a
        policy it could be steered into using for something else."""
        import inspect

        from app.routers import waitlist

        source = inspect.getsource(waitlist.join_waitlist)
        assert "argus_join_waitlist" in source
        assert "INSERT INTO waitlist" not in source


class TestRateLimiting:
    def test_repeated_attempts_are_refused(self, client):
        """The endpoint is public and writes a row, so it is a way to fill a
        table if nothing stops it."""
        codes = []
        for _ in range(25):
            codes.append(
                client.post(
                    "/api/v1/waitlist",
                    json={"email": f"flood-{uuid.uuid4().hex[:8]}@example.com"},
                ).status_code
            )

        assert 429 in codes, (
            "twenty-five submissions in a row were all accepted, so "
            f"nothing limits this endpoint: {codes}"
        )
