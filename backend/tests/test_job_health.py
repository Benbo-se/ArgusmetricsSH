"""/health reports whether the scheduled jobs are still running.

A scheduled job has nobody waiting for it, so when one stops the only symptom
is something that should have happened and did not. That is not hypothetical:
the traffic-spike job ran hourly for weeks doing nothing, and raised no error
because from its own point of view nothing was wrong.

These check the endpoint an uptime monitor would watch.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text


def _record(db, job, seconds_ago=None, failures=0, error=None):
    when = (
        None if seconds_ago is None
        else datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    )
    db.execute(
        text(
            "INSERT INTO job_runs (job_name, last_success_at, consecutive_failures, last_error) "
            "VALUES (:n, :t, :f, :e) "
            "ON CONFLICT (job_name) DO UPDATE SET last_success_at = EXCLUDED.last_success_at, "
            "  consecutive_failures = EXCLUDED.consecutive_failures, last_error = EXCLUDED.last_error"
        ),
        {"n": job, "t": when, "f": failures, "e": error},
    )
    db.commit()


class TestHealthReportsJobs:
    def test_a_recent_success_is_healthy(self, client, db):
        for job in ("daily_cleanup", "email_reports", "traffic_alerts"):
            _record(db, job, seconds_ago=60)

        body = client.get("/health").json()

        assert body["status"] == "healthy", body
        assert body["stalled_jobs"] == []

    def test_a_stalled_job_makes_the_instance_degraded(self, client, db):
        """Degraded rather than unhealthy: the site is serving and tracking is
        recording. Something that should be happening is not."""
        for job in ("daily_cleanup", "email_reports"):
            _record(db, job, seconds_ago=60)
        _record(db, "traffic_alerts", seconds_ago=9 * 3600)  # limit is 3 hours

        body = client.get("/health").json()

        assert body["status"] == "degraded", body
        assert body["stalled_jobs"] == ["traffic_alerts"]
        assert body["jobs"]["traffic_alerts"]["overdue"] is True

    def test_the_last_error_is_reported(self, client, db):
        """Kept after a later success too, so a job failing every other night
        is visible rather than looking fine every second morning."""
        for job in ("daily_cleanup", "email_reports", "traffic_alerts"):
            _record(db, job, seconds_ago=60)
        _record(db, "traffic_alerts", seconds_ago=60, failures=3, error="SMTP timeout")

        job = client.get("/health").json()["jobs"]["traffic_alerts"]

        assert job["consecutive_failures"] == 3
        assert job["last_error"] == "SMTP timeout"

    def test_a_job_that_has_never_run_is_not_immediately_overdue(self, client, db):
        """Otherwise every fresh deployment reports degraded until the first
        nightly job fires, which teaches people to ignore the endpoint."""
        db.execute(text("DELETE FROM job_runs"))
        db.commit()

        body = client.get("/health").json()

        # This process started seconds ago, so nothing has had its chance yet.
        assert body["status"] == "healthy", body
        assert body["jobs"]["daily_cleanup"]["seconds_since_success"] is None
        assert body["jobs"]["daily_cleanup"]["overdue"] is False


class TestTheJobsRecordThemselves:
    def test_a_run_records_start_success_and_duration(self, engine):
        """The bookkeeping is in _single_runner, which every job passes through.

        This deliberately uses `engine` rather than the `db` fixture. The job
        opens its own session through SessionLocal, and the test transaction
        would still be holding the row lock on job_runs, so the two would wait
        on each other until something timed out. Anything that runs the real
        scheduled code has to stay outside the rolled-back transaction.

        The row it writes therefore survives the test, which is correct: it is
        one row per job, updated in place, and it is exactly what a real run
        would have left.
        """
        from datetime import datetime, timedelta, timezone

        from app.scheduled_tasks import traffic_alerts_task

        before = datetime.now(timezone.utc) - timedelta(seconds=1)
        traffic_alerts_task()

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT last_started_at, last_success_at, consecutive_failures,"
                    "       last_duration_ms FROM job_runs WHERE job_name = 'traffic_alerts'"
                )
            ).first()

        assert row is not None, "the job ran and recorded nothing"
        assert row.last_started_at >= before, "last_started_at was not updated by this run"
        assert row.last_success_at >= before, "it finished but did not record success"
        assert row.consecutive_failures == 0
        assert row.last_duration_ms is not None
