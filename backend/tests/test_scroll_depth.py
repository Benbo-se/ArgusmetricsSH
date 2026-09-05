"""Scroll depth, from the tracking endpoint to the column the dashboard reads.

The column, the query and the dashboard have all existed since the beginning.
The tracker never sent the value, so `avg_scroll` was fed by nothing: in
development the column looked populated because the seed data fills it, and in
production it was empty. Sixth time in this codebase that a feature was
complete except for the wire between two halves.

These drive the real endpoints, because that is the part that was missing.
"""
from sqlalchemy import text


def _record_pageview(client, website, path="/an-article"):
    response = client.post(
        "/api/v1/analytics/track",
        json={"tracking_code": website["tracking_code"], "path": path},
    )
    assert response.status_code == 200, response.text[:200]


def _send_depth(client, website, depth, path="/an-article"):
    return client.post(
        "/api/v1/analytics/track-scroll",
        json={"tracking_code": website["tracking_code"], "path": path, "depth": depth},
    )


def _stored(db, path="/an-article"):
    return db.execute(
        text("SELECT scroll_depth FROM pageviews WHERE path = :p ORDER BY \"timestamp\" DESC LIMIT 1"),
        {"p": path},
    ).scalar()


class TestTheDepthReachesTheColumn:
    def test_a_pageview_starts_with_no_depth(self, client, website, db):
        """It is not known until the visitor leaves."""
        _record_pageview(client, website)
        assert _stored(db) is None

    def test_sending_it_fills_the_column(self, client, website, db):
        _record_pageview(client, website)

        response = _send_depth(client, website, 64)

        assert response.status_code == 200
        assert _stored(db) == 64

    def test_it_only_ever_increases(self, client, website, db):
        """A visitor who returns and leaves at the top keeps the deeper value."""
        _record_pageview(client, website)
        _send_depth(client, website, 90)
        _send_depth(client, website, 30)

        assert _stored(db) == 90

    def test_it_costs_nothing_against_the_monthly_limit(self, client, website, db):
        """The visit was counted when the page loaded.

        Charging again would make a visitor who reads to the bottom cost more
        than one who leaves at once, which is the opposite of what anyone
        wants to encourage.
        """
        _record_pageview(client, website)
        before = db.execute(
            text(
                "SELECT events FROM account_usage WHERE owner_email = :e "
                "   AND period_start = date_trunc('month', now())::date"
            ),
            {"e": website["email"]},
        ).scalar()

        _send_depth(client, website, 55)

        after = db.execute(
            text(
                "SELECT events FROM account_usage WHERE owner_email = :e "
                "   AND period_start = date_trunc('month', now())::date"
            ),
            {"e": website["email"]},
        ).scalar()
        assert after == before


class TestItRefusesWhatItShould:
    def test_an_unknown_tracking_code(self, client):
        response = client.post(
            "/api/v1/analytics/track-scroll",
            json={"tracking_code": "nope", "path": "/x", "depth": 50},
        )
        assert response.status_code == 400

    def test_a_depth_outside_the_range(self, client, website):
        _record_pageview(client, website)
        for depth in (0, 101, -5):
            response = _send_depth(client, website, depth)
            assert response.status_code == 422, f"depth {depth} was accepted"

    def test_a_path_with_no_pageview_is_not_an_error(self, client, website, db):
        """The visit may have aged out, and the browser has already left.

        Answering with an error would achieve nothing except noise in a
        console nobody is watching.
        """
        response = _send_depth(client, website, 40, path="/never-visited")
        assert response.status_code == 200
        assert _stored(db, "/never-visited") is None
