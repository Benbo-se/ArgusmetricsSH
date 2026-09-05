"""The metrics endpoint, and the fact that it is shut by default.

What it exposes is a business number: pageviews per hour, how many websites,
how many accounts. An instance that published that to anyone who guessed the
path would be leaking its customers' traffic volume, so the endpoint answers
404 until a token is configured.

404 rather than 401, deliberately: an unauthenticated caller should not learn
that the endpoint exists.
"""
from app.config import settings


class TestItIsShutByDefault:
    def test_no_token_means_no_endpoint(self, client):
        assert settings.METRICS_TOKEN is None
        assert client.get("/metrics").status_code == 404

    def test_a_wrong_token_looks_the_same_as_no_endpoint(self, client, monkeypatch):
        monkeypatch.setattr(settings, "METRICS_TOKEN", "the-real-one")

        assert client.get("/metrics").status_code == 404
        assert client.get(
            "/metrics", headers={"Authorization": "Bearer wrong"}
        ).status_code == 404
        assert client.get(
            "/metrics", headers={"Authorization": "the-real-one"}
        ).status_code == 404, "a bare token without the Bearer prefix was accepted"


class TestWhatItReports:
    def test_the_right_token_gets_the_numbers(self, client, monkeypatch):
        monkeypatch.setattr(settings, "METRICS_TOKEN", "secret")

        response = client.get("/metrics", headers={"Authorization": "Bearer secret"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert "argus_pageviews_recent" in response.text

    def test_every_metric_declares_itself_once(self, client, monkeypatch):
        """Prometheus rejects a body that repeats HELP or TYPE for a name.

        The first version emitted them once per label, so the two pageview
        windows each carried their own header and the whole scrape would have
        been refused.
        """
        import collections

        monkeypatch.setattr(settings, "METRICS_TOKEN", "secret")
        body = client.get("/metrics", headers={"Authorization": "Bearer secret"}).text

        for prefix in ("# HELP", "# TYPE"):
            names = [
                line.split()[2] for line in body.splitlines() if line.startswith(prefix)
            ]
            repeated = [n for n, c in collections.Counter(names).items() if c > 1]
            assert not repeated, f"{prefix} repeated for {repeated}"

    def test_uptime_is_an_uptime(self, client, monkeypatch):
        """It read a wall clock against a monotonic start and reported 1787928331.

        Fifty-six years of uptime is the sort of number a dashboard shows
        without anyone noticing, so it is worth pinning.
        """
        monkeypatch.setattr(settings, "METRICS_TOKEN", "secret")
        body = client.get("/metrics", headers={"Authorization": "Bearer secret"}).text

        line = next(
            l for l in body.splitlines()
            if l.startswith("argus_uptime_seconds ")
        )
        seconds = int(line.split()[1])
        assert 0 <= seconds < 86400 * 365, f"uptime reported as {seconds} seconds"

    def test_a_failing_query_does_not_take_the_endpoint_down(self, client, monkeypatch):
        """Monitoring that can cause an outage is worse than none."""
        monkeypatch.setattr(settings, "METRICS_TOKEN", "secret")
        monkeypatch.setattr(
            "app.metrics._scalar", lambda *a, **k: None
        )

        response = client.get("/metrics", headers={"Authorization": "Bearer secret"})
        assert response.status_code == 200
