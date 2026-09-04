"""
Scheduled Background Tasks

Handles periodic tasks like:
- Daily cleanup of inactive accounts
- Session cleanup
- Analytics aggregation
"""
import logging
import time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


from contextlib import contextmanager


def _record_start(db, job_name: str) -> None:
    """Note that the job began. Separate from success on purpose: a job that
    fails every night still has a recent start, and only one of the two tells
    you it is working."""
    from sqlalchemy import text as _text

    db.execute(
        _text(
            "INSERT INTO job_runs (job_name, last_started_at) VALUES (:n, now()) "
            "ON CONFLICT (job_name) DO UPDATE SET last_started_at = now()"
        ),
        {"n": job_name},
    )
    db.commit()


def _record_success(db, job_name: str, started: float) -> None:
    from sqlalchemy import text as _text

    db.execute(
        _text(
            "UPDATE job_runs SET last_success_at = now(), consecutive_failures = 0,"
            "       last_duration_ms = :ms "
            " WHERE job_name = :n"
        ),
        {"n": job_name, "ms": int((time.monotonic() - started) * 1000)},
    )
    db.commit()


def _record_failure(db, job_name: str, exc: Exception, started: float) -> None:
    """Keep the message after a later success too, so a job that fails every
    other night is visible rather than looking healthy every second morning."""
    from sqlalchemy import text as _text

    try:
        db.rollback()
        db.execute(
            _text(
                "UPDATE job_runs SET last_error = :e,"
                "       consecutive_failures = consecutive_failures + 1,"
                "       last_duration_ms = :ms "
                " WHERE job_name = :n"
            ),
            {"n": job_name, "e": str(exc)[:2000],
             "ms": int((time.monotonic() - started) * 1000)},
        )
        db.commit()
    except Exception:
        # Never let bookkeeping mask the real failure.
        logger.exception(f"[SCHEDULED] Could not record failure for {job_name}")


@contextmanager
def _single_runner(lock_key: int, job_name: str):
    """Run a scheduled job on at most one process.

    The scheduler is a per-process object, so with multiple uvicorn workers
    every job would otherwise fire once per worker (duplicate cleanup runs,
    duplicate report emails). A Postgres advisory lock makes the first worker
    to arrive the only one that runs it.
    """
    from sqlalchemy import text
    from app.database import SessionLocal, set_rls_context

    db = SessionLocal()
    acquired = False
    started = time.monotonic()
    try:
        acquired = bool(db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key}).scalar())
        if not acquired:
            logger.info(f"[SCHEDULED] Job {lock_key} already running in another worker - skipping")
            yield acquired
            return

        set_rls_context(db, context="job")
        _record_start(db, job_name)
        try:
            yield acquired
        except Exception as exc:
            _record_failure(db, job_name, exc, started)
            raise
        _record_success(db, job_name, started)
    finally:
        if acquired:
            db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key})
            db.commit()
        db.close()


def cleanup_task():
    """Daily cleanup task - runs at 2 AM UTC."""
    from app.services.cleanup_service import run_daily_cleanup

    logger.info(f"[SCHEDULED] Running daily cleanup at {datetime.now(timezone.utc)}")
    try:
        with _single_runner(918_271_001, "daily_cleanup") as acquired:
            if acquired:
                run_daily_cleanup()
    except Exception as e:
        logger.error(f"[SCHEDULED] Error running cleanup task: {e}", exc_info=True)


def email_reports_task():
    """Daily email-reports dispatch - sends every weekly/monthly report that is
    due today (users configure frequency + day per website)."""
    from app.database import SessionLocal, set_rls_context
    from app.services.email_reports_service import EmailReportsService

    logger.info(f"[SCHEDULED] Running email-reports dispatch at {datetime.now(timezone.utc)}")
    db = SessionLocal()
    set_rls_context(db, context="job")
    try:
        with _single_runner(918_271_002, "email_reports") as acquired:
            if acquired:
                stats = EmailReportsService(db).send_scheduled_reports()
                logger.info(f"[SCHEDULED] Email reports done: {stats}")
    except Exception as e:
        logger.error(f"[SCHEDULED] Error sending email reports: {e}", exc_info=True)
    finally:
        db.close()


def traffic_alerts_task():
    """Hourly traffic-spike alert check.

    AlertService could already detect a spike and email about it, but nothing
    ever called it: the routers only read and write the settings, so a site
    with alerts enabled would never actually hear about a spike. This is the
    job that connects the two.

    check_traffic_spike() compares the last hour against the weekly hourly
    baseline and returns None unless the site has email alerts enabled, so
    sites that never opted in cost one cheap query and nothing else.
    """
    from app.database import SessionLocal, set_rls_context
    from app.models.website import Website
    from app.services.alert_service import AlertService

    logger.info(f"[SCHEDULED] Running traffic-spike alert check at {datetime.now(timezone.utc)}")
    db = SessionLocal()
    set_rls_context(db, context="job")
    try:
        with _single_runner(918_271_003, "traffic_alerts") as acquired:
            if not acquired:
                return

            alert_service = AlertService(db)
            websites = db.query(Website).filter(Website.is_active == True).all()
            sent = 0

            for website in websites:
                try:
                    spike = alert_service.check_traffic_spike(website.id)
                    if not spike:
                        continue
                    if alert_service.send_spike_alert(
                        website_id=website.id,
                        spike_data=spike,
                        user_email=website.user_email,
                        website_name=website.name,
                    ):
                        sent += 1
                except Exception as e:
                    # One bad site must not stop alerts for every other site.
                    logger.error(
                        f"[SCHEDULED] Error checking alerts for website {website.id}: {e}",
                        exc_info=True,
                    )

            logger.info(f"[SCHEDULED] Traffic-spike check done: {sent} alert(s) sent")
    except Exception as e:
        logger.error(f"[SCHEDULED] Error running traffic-spike alerts: {e}", exc_info=True)
    finally:
        db.close()


def start_scheduler():
    """Initialize and start the background scheduler."""
    scheduler = BackgroundScheduler(timezone="UTC")

    # Schedule daily cleanup at 2 AM UTC
    scheduler.add_job(
        cleanup_task,
        trigger=CronTrigger(hour=2, minute=0),
        id="daily_cleanup",
        name="Daily cleanup of inactive accounts",
        replace_existing=True
    )

    # Dispatch due weekly/monthly email reports at 7 AM UTC (morning in EU)
    scheduler.add_job(
        email_reports_task,
        trigger=CronTrigger(hour=7, minute=0),
        id="email_reports",
        name="Send due weekly/monthly email reports",
        replace_existing=True
    )

    # Check for traffic spikes hourly (the alert compares the last hour to the
    # weekly hourly baseline, so checking more often than hourly is pointless)
    scheduler.add_job(
        traffic_alerts_task,
        trigger=CronTrigger(minute=5),
        id="traffic_alerts",
        name="Check for traffic spikes and send alerts",
        replace_existing=True
    )

    scheduler.start()
    logger.info(
        "Background scheduler started - cleanup 02:00 UTC, email reports 07:00 UTC, "
        "traffic-spike alerts hourly at :05"
    )

    return scheduler


# Global scheduler instance
_scheduler = None


def get_scheduler():
    """Get or create global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = start_scheduler()
    return _scheduler
