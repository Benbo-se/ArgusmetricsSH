"""A job whose sub-task failed is a failed job.

Every sub-task of the nightly cleanup caught its own exception, logged it and
returned 0, so the job as a whole finished normally and recorded success. /health
reads job_runs, so it could not see a cleanup that had been failing for weeks.
The same went for email reports that failed to send and for sites whose alert
check raised.
"""
import uuid

import pytest
from sqlalchemy import text

from app.database import set_rls_context


def _job(engine, name):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT consecutive_failures, last_error, last_success_at "
                 "FROM job_runs WHERE job_name = :n"),
            {"n": name},
        ).first()


@pytest.fixture
def clean_job_row(engine):
    """These runs write job_runs for real, so put the failure count back."""
    yield
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE job_runs SET consecutive_failures = 0, last_error = NULL "
                 "WHERE job_name IN ('email_reports', 'traffic_alerts')")
        )


class TestCleanup:
    def test_a_failing_sub_task_fails_the_run_but_not_the_others(self, db, monkeypatch):
        from app.services import cleanup_service
        from app.services.cleanup_service import CleanupFailed, CleanupService

        set_rls_context(db, context="job")
        email = f"cleanup-{uuid.uuid4().hex[:8]}@example.com"
        db.execute(
            text("INSERT INTO users (email, is_verified, created_at) "
                 "VALUES (:e, false, now() - interval '30 days')"),
            {"e": email},
        )
        db.execute(
            text("INSERT INTO waitlist (email, created_at) VALUES (:e, now() - interval '400 days')"),
            {"e": email},
        )
        db.commit()
        # A real failure inside one sub-task: querying something that is not a model.
        monkeypatch.setattr(cleanup_service, "UserSession", object())

        with pytest.raises(CleanupFailed) as failed:
            CleanupService(db).run_all_cleanup_tasks()

        assert "cleanup_expired_sessions" in str(failed.value)
        # The unverified account goes in a sub-task before the failing one, the waitlist
        # entry in one after it.
        assert db.execute(text("SELECT 1 FROM users WHERE email = :e"), {"e": email}).scalar() is None, (
            "one failing sub-task stopped the ones before it"
        )
        assert db.execute(text("SELECT 1 FROM waitlist WHERE email = :e"), {"e": email}).scalar() is None, (
            "one failing sub-task stopped the ones after it"
        )

    def test_a_clean_run_still_returns_its_counts(self, db):
        from app.services.cleanup_service import CleanupService

        set_rls_context(db, context="job")

        result = CleanupService(db).run_all_cleanup_tasks()

        assert len(result) == 4


class TestEmailReports:
    def test_failed_reports_are_a_failed_job(self, engine, monkeypatch, clean_job_row):
        from app.scheduled_tasks import email_reports_task
        from app.services.email_reports_service import EmailReportsService

        monkeypatch.setattr(
            EmailReportsService, "send_scheduled_reports",
            lambda self: {"weekly_attempted": 2, "weekly_sent": 1, "monthly_attempted": 0,
                          "monthly_sent": 0, "total_failures": 1},
        )
        before = (_job(engine, "email_reports") or (0,))[0]

        email_reports_task()

        row = _job(engine, "email_reports")
        assert row.consecutive_failures == before + 1, "the failed report was recorded as a success"
        assert "1" in row.last_error

    def test_all_reports_sent_is_a_success(self, engine, monkeypatch, clean_job_row):
        from app.scheduled_tasks import email_reports_task
        from app.services.email_reports_service import EmailReportsService

        monkeypatch.setattr(
            EmailReportsService, "send_scheduled_reports",
            lambda self: {"weekly_attempted": 1, "weekly_sent": 1, "monthly_attempted": 0,
                          "monthly_sent": 0, "total_failures": 0},
        )

        email_reports_task()

        assert _job(engine, "email_reports").consecutive_failures == 0


class TestTrafficAlerts:
    @pytest.fixture
    def committed_site(self, engine):
        suffix = uuid.uuid4().hex[:8]
        email = f"alerts-{suffix}@example.com"
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO users (email, is_verified, created_at) VALUES (:e, true, now())"),
                {"e": email},
            )
            site = conn.execute(
                text(
                    "INSERT INTO websites (name, domain, user_email, tracking_code,"
                    "  verification_token, is_verified, is_active, email_reports_enabled,"
                    "  is_public, public_password_enabled, created_at) "
                    "VALUES ('s', :d, :e, :tc, :vt, true, true, false, false, false, now()) "
                    "RETURNING id"
                ),
                {"d": f"https://{suffix}.example.com", "e": email, "tc": suffix, "vt": f"t-{suffix}"},
            ).scalar()
        yield site
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE email = :e"), {"e": email})

    def test_a_site_whose_check_raises_fails_the_job_after_the_others_ran(
        self, engine, committed_site, monkeypatch, clean_job_row
    ):
        from app.scheduled_tasks import traffic_alerts_task
        from app.services.alert_service import AlertService

        checked = []

        def check(self, website_id):
            checked.append(website_id)
            raise RuntimeError("boom")

        monkeypatch.setattr(AlertService, "check_traffic_spike", check)
        before = (_job(engine, "traffic_alerts") or (0,))[0]

        traffic_alerts_task()

        assert committed_site in checked
        row = _job(engine, "traffic_alerts")
        assert row.consecutive_failures == before + 1, "a raising site was recorded as a success"
        assert "boom" in row.last_error
