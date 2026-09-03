"""Exports, reports and the read-only endpoints, driven against real data.

The rest of the mutating routes are covered in test_feature_wiring. These are
the ones that produce something for a person to look at, and the failure they
hide is different: not a button that writes nothing, but a report that renders
an empty file and looks like a quiet week.

So every test here puts real rows in first and then asserts the output
contains them.
"""
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text


def _add_pageviews(db, website_id, paths, hours_ago=1):
    when = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    for path in paths:
        db.execute(
            text(
                "INSERT INTO pageviews "
                "  (website_id, path, visitor_hash, timestamp, browser, device_type) "
                "VALUES (:w, :p, :h, :t, 'Chrome', 'desktop')"
            ),
            {"w": website_id, "p": path, "h": uuid.uuid4().hex[:16], "t": when},
        )
    db.commit()


RANGE = "start_date=2020-01-01&end_date=2099-01-01"


class TestExports:
    def test_csv_contains_the_pageviews(self, owner_client, db, website):
        """An export that returns headers and no rows looks like a quiet week."""
        _add_pageviews(db, website["id"], ["/", "/pricing", "/pricing"])

        response = owner_client.get(
            f"/api/v1/analytics/export/{website['id']}/csv?{RANGE}"
        )

        assert response.status_code == 200, response.text
        rows = list(csv.reader(io.StringIO(response.text)))
        assert len(rows) > 1, "the export has a header and nothing else"
        assert "/pricing" in response.text, "a path that exists is missing from the export"

    def test_csv_is_offered_as_a_download(self, owner_client, db, website):
        _add_pageviews(db, website["id"], ["/"])

        response = owner_client.get(
            f"/api/v1/analytics/export/{website['id']}/csv?{RANGE}"
        )

        disposition = response.headers.get("content-disposition", "")
        assert "attachment" in disposition, (
            "the CSV renders in the browser instead of downloading"
        )

    def test_json_contains_the_pageviews(self, owner_client, db, website):
        _add_pageviews(db, website["id"], ["/", "/docs"])

        response = owner_client.get(
            f"/api/v1/analytics/export/{website['id']}/json?{RANGE}"
        )

        assert response.status_code == 200, response.text
        assert "/docs" in response.text, "a path that exists is missing from the export"

    def test_an_export_cannot_reach_another_website(self, owner_client, db, website):
        db.execute(
            text(
                "INSERT INTO users (email, is_verified, created_at) "
                "VALUES ('someone-else@example.com', true, now()) "
                "ON CONFLICT (email) DO NOTHING"
            )
        )
        other = db.execute(
            text(
                "INSERT INTO websites (name, domain, user_email, tracking_code,"
                "                      verification_token, is_verified, is_active,"
                "                      email_reports_enabled, is_public,"
                "                      public_password_enabled, created_at) "
                "VALUES ('other', :d, 'someone-else@example.com', :tc, :vt,"
                "        true, true, false, false, false, now()) RETURNING id"
            ),
            {
                "d": f"https://other-{uuid.uuid4().hex[:8]}.example.com",
                "tc": uuid.uuid4().hex[:8],
                "vt": uuid.uuid4().hex,
            },
        ).scalar()
        db.commit()

        response = owner_client.get(
            f"/api/v1/analytics/export/{other}/csv?{RANGE}"
        )

        assert response.status_code == 404


class TestRealtime:
    def test_it_counts_a_recent_visitor(self, owner_client, db, website):
        _add_pageviews(db, website["id"], ["/"], hours_ago=0)

        response = owner_client.get(f"/api/v1/analytics/realtime/{website['id']}")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body.get("current_visitors", 0) >= 1, (
            f"a visitor from moments ago is not counted: {body}"
        )


class TestAnomalies:
    def test_the_endpoint_answers_for_a_website_with_no_history(
        self, owner_client, db, website
    ):
        """A new site has nothing to compare against, which is not an error."""
        response = owner_client.get(f"/api/v1/anomalies/{website['id']}")

        assert response.status_code == 200, response.text


class TestTestReport:
    def test_it_refuses_before_reports_are_configured(self, owner_client, db, website):
        """Otherwise the button reports success and sends to nobody."""
        response = owner_client.post(
            "/api/v1/email-reports/send-test",
            json={"website_id": website["id"]},
        )

        assert response.status_code == 400
        assert "configure" in response.text.lower()

    def test_it_sends_once_reports_are_configured(self, owner_client, db, website):
        _add_pageviews(db, website["id"], ["/", "/pricing"])
        owner_client.post(
            "/api/v1/email-reports/configure",
            json={
                "website_id": website["id"],
                "enabled": True,
                "frequency": "weekly",
                "recipient": "reports@example.com",
                "day": 1,
            },
        )

        response = owner_client.post(
            "/api/v1/email-reports/send-test",
            json={"website_id": website["id"]},
        )

        assert response.status_code == 200, response.text
        assert response.json()["recipient"] == "reports@example.com"


    def test_the_report_contains_the_numbers(self, owner_client, db, website, monkeypatch):
        """A report that sends is not the same as a report worth reading.

        Email runs in stub mode here, so a green send only proves the message
        reached the email layer. This captures what that layer was handed and
        checks the traffic is actually in it, since a report that renders zero
        for a busy week is worse than one that fails.
        """
        from app.services import email_service as email_module

        captured = {}

        def _capture(to, subject, html_content, **kwargs):
            captured["to"] = to
            captured["subject"] = subject
            captured["html"] = html_content
            return True

        monkeypatch.setattr(email_module.email_service, "send_email", _capture)

        _add_pageviews(db, website["id"], ["/", "/pricing", "/pricing"])
        owner_client.post(
            "/api/v1/email-reports/configure",
            json={
                "website_id": website["id"],
                "enabled": True,
                "frequency": "weekly",
                "recipient": "reports@example.com",
                "day": 1,
            },
        )

        response = owner_client.post(
            "/api/v1/email-reports/send-test",
            json={"website_id": website["id"]},
        )

        assert response.status_code == 200, response.text
        assert captured, "nothing was handed to the email layer"
        assert website["domain"] in captured["html"] or "Test site" in captured["html"], (
            "the report does not say which website it is about"
        )
        assert "/pricing" in captured["html"], (
            "the report was sent without the traffic it is reporting on"
        )


class TestDomainVerification:
    def test_an_unverifiable_domain_is_reported_not_crashed(
        self, owner_client, db, website
    ):
        """The DNS lookup will not find a record for a test domain.

        What matters is that it says so rather than raising, since a network
        call inside a request is the easiest thing in this codebase to leave
        unguarded.
        """
        db.execute(
            text("UPDATE websites SET is_verified = false WHERE id = :w"),
            {"w": website["id"]},
        )
        db.commit()

        response = owner_client.post(
            f"/api/v1/websites/{website['id']}/verify-domain"
        )

        assert response.status_code in (200, 400), response.text
        assert response.status_code != 500, "the DNS lookup crashed the request"
