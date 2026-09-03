"""The scheduled jobs, which nobody watches until they are wrong.

Three run on a timer: nightly cleanup, the email report dispatch, and the
hourly traffic spike check. A scheduled job fails differently from a request.
Nobody is waiting for a response, so it can do nothing at all for months and
the only symptom is data that should have been deleted, or reports that never
arrived.

The tasks themselves open their own session through SessionLocal, so these
test the services underneath with the test's rolled-back session, plus the
advisory lock that keeps a job from running twice.

They also run in the job context, which is the only one allowed across
tenants. That is deliberate and worth pinning: a job that forgot to declare
it would silently process nothing at all.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.database import set_rls_context


class TestAdvisoryLock:
    def test_a_second_holder_is_refused(self, engine):
        """With several workers the scheduler exists once per process.

        Without this lock every job fires once per worker: duplicate cleanup
        runs and, worse, duplicate report emails to customers.
        """
        key = 918_271_999

        first = engine.connect()
        second = engine.connect()
        try:
            got_first = first.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": key}
            ).scalar()
            got_second = second.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": key}
            ).scalar()

            assert got_first is True
            assert got_second is False, "two workers can run the same job at once"
        finally:
            first.execute(text("SELECT pg_advisory_unlock_all()"))
            first.commit()
            second.execute(text("SELECT pg_advisory_unlock_all()"))
            second.commit()
            first.close()
            second.close()

    def test_the_lock_keys_are_distinct(self):
        """One key for all three jobs would let cleanup block the reports."""
        import inspect

        from app import scheduled_tasks

        source = inspect.getsource(scheduled_tasks)
        keys = [
            line.split("_single_runner(")[1].split(")")[0].strip()
            for line in source.splitlines()
            if "_single_runner(" in line and "def " not in line
        ]

        assert len(keys) >= 2, f"expected several jobs, found {keys}"
        assert len(set(keys)) == len(keys), f"two jobs share a lock key: {keys}"


class TestRetention:
    def _two_pageviews(self, db, website_id):
        """One from long ago, one from now."""
        now = datetime.now(timezone.utc)
        for label, when in (("ancient", now - timedelta(days=5000)), ("fresh", now)):
            db.execute(
                text(
                    "INSERT INTO pageviews (website_id, path, visitor_hash, timestamp) "
                    "VALUES (:w, :p, :h, :t)"
                ),
                {"w": website_id, "p": f"/{label}", "h": uuid.uuid4().hex[:16], "t": when},
            )
        db.commit()

    def _paths(self, db, website_id):
        return {
            r[0]
            for r in db.execute(
                text("SELECT path FROM pageviews WHERE website_id = :w"),
                {"w": website_id},
            )
        }

    def test_zero_days_keeps_everything(self, db, website, monkeypatch):
        """The default, and a contract: 0 means keep forever.

        Worth pinning, because a change that made 0 mean "delete everything
        older than today" would quietly destroy every customer's history on
        the next nightly run.
        """
        from app.config import settings
        from app.services.cleanup_service import CleanupService

        monkeypatch.setattr(settings, "DATA_RETENTION_DAYS", 0)
        set_rls_context(db, context="job")
        self._two_pageviews(db, website["id"])

        CleanupService(db).purge_old_event_data()

        assert self._paths(db, website["id"]) == {"/ancient", "/fresh"}, (
            "retention deleted data with the window switched off"
        )

    def test_a_window_purges_past_it_and_keeps_the_rest(self, db, website, monkeypatch):
        from app.config import settings
        from app.services.cleanup_service import CleanupService

        monkeypatch.setattr(settings, "DATA_RETENTION_DAYS", 30)
        set_rls_context(db, context="job")
        self._two_pageviews(db, website["id"])

        CleanupService(db).purge_old_event_data()

        remaining = self._paths(db, website["id"])
        assert "/fresh" in remaining, "retention deleted data inside the window"
        assert "/ancient" not in remaining, "data past the window is still there"

    def test_expired_sessions_are_deleted(self, db, website):
        from app.services.cleanup_service import CleanupService

        set_rls_context(db, context="job")
        for label, expires in (
            ("stale", datetime.now(timezone.utc) - timedelta(days=1)),
            ("live", datetime.now(timezone.utc) + timedelta(days=1)),
        ):
            db.execute(
                text(
                    "INSERT INTO sessions (token, user_email, expires_at, created_at) "
                    "VALUES (:t, :e, :x, now())"
                ),
                {"t": f"{label}-{uuid.uuid4().hex}", "e": website["email"], "x": expires},
            )
        db.commit()

        CleanupService(db).cleanup_expired_sessions()

        left = db.execute(
            text("SELECT count(*) FROM sessions WHERE user_email = :e"),
            {"e": website["email"]},
        ).scalar()
        assert left == 1, f"expected only the unexpired session to survive, found {left}"


class TestEmailReportDispatch:
    def test_it_finds_a_website_scheduled_for_today(self, db, website):
        """The query that decides whether anyone gets a report at all."""
        from app.services.email_reports_service import EmailReportsService

        set_rls_context(db, context="job")
        db.execute(
            text(
                "UPDATE websites SET email_reports_enabled = true,"
                "       email_reports_frequency = 'weekly',"
                "       email_reports_recipient = 'reports@example.com',"
                "       email_reports_day = 3 WHERE id = :w"
            ),
            {"w": website["id"]},
        )
        db.commit()

        due = EmailReportsService(db).get_websites_due_for_report("weekly", 3)

        assert any(w.id == website["id"] for w in due), (
            "a website scheduled for today is not in the dispatch list"
        )

    def test_it_skips_a_website_scheduled_for_another_day(self, db, website):
        from app.services.email_reports_service import EmailReportsService

        set_rls_context(db, context="job")
        db.execute(
            text(
                "UPDATE websites SET email_reports_enabled = true,"
                "       email_reports_frequency = 'weekly',"
                "       email_reports_recipient = 'reports@example.com',"
                "       email_reports_day = 3 WHERE id = :w"
            ),
            {"w": website["id"]},
        )
        db.commit()

        due = EmailReportsService(db).get_websites_due_for_report("weekly", 5)

        assert not any(w.id == website["id"] for w in due), (
            "a website is sent a report on the wrong day"
        )

    def test_it_skips_a_website_with_reports_switched_off(self, db, website):
        from app.services.email_reports_service import EmailReportsService

        set_rls_context(db, context="job")
        db.execute(
            text(
                "UPDATE websites SET email_reports_enabled = false,"
                "       email_reports_frequency = 'weekly',"
                "       email_reports_day = 3 WHERE id = :w"
            ),
            {"w": website["id"]},
        )
        db.commit()

        due = EmailReportsService(db).get_websites_due_for_report("weekly", 3)

        assert not any(w.id == website["id"] for w in due), (
            "reports are sent to someone who turned them off"
        )


class TestTrafficAlerts:
    def test_a_website_without_settings_is_skipped(self, db, website):
        """Which was every website until the settings page existed."""
        from app.services.alert_service import AlertService

        set_rls_context(db, context="job")

        assert AlertService(db).check_traffic_spike(website["id"]) is None

    def test_the_check_runs_once_settings_exist(self, db, website):
        """No spike to find here; what matters is that it gets past the gate."""
        from app.services.alert_service import AlertService

        set_rls_context(db, context="job")
        db.execute(
            text(
                "INSERT INTO alert_settings "
                "  (website_id, spike_threshold, email_enabled, alert_email) "
                "VALUES (:w, 2.0, true, :e)"
            ),
            {"w": website["id"], "e": website["email"]},
        )
        db.commit()

        # Returning None means no spike, which is the correct answer for a
        # website with no traffic. The assertion is that it does not raise.
        AlertService(db).check_traffic_spike(website["id"])
