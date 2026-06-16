"""
Scheduled Background Tasks

Handles periodic tasks like:
- Daily cleanup of inactive accounts
- Session cleanup
- Analytics aggregation
"""
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def cleanup_task():
    """Daily cleanup task - runs at 2 AM UTC."""
    from app.services.cleanup_service import run_daily_cleanup

    logger.info(f"[SCHEDULED] Running daily cleanup at {datetime.now(timezone.utc)}")
    try:
        run_daily_cleanup()
    except Exception as e:
        logger.error(f"[SCHEDULED] Error running cleanup task: {e}", exc_info=True)


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

    scheduler.start()
    logger.info("Background scheduler started - Daily cleanup will run at 02:00 UTC")

    return scheduler


# Global scheduler instance
_scheduler = None


def get_scheduler():
    """Get or create global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = start_scheduler()
    return _scheduler
