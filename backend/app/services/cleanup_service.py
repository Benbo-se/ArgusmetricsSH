"""
Cleanup Service for inactive accounts and expired data.

Handles automated cleanup tasks:
- Delete unverified accounts after 7 days
- Delete empty accounts (no websites) after 30 days of inactivity
- Clean up expired sessions
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from app.models.user import User
from app.models.session import Session as UserSession
from app.models.website import Website

logger = logging.getLogger(__name__)


def _mask(email) -> str:
    """Redact an email for logging (PII-safe)."""
    from app.utils.security import mask_email
    return mask_email(email)


class CleanupService:
    """Service for cleaning up inactive accounts and expired data."""

    def __init__(self, db: Session):
        """Initialize cleanup service with database session."""
        self.db = db

    def cleanup_unverified_accounts(self, days: int = 7) -> int:
        """
        Delete unverified accounts older than specified days.

        Args:
            days: Number of days after which unverified accounts are deleted (default: 7)

        Returns:
            int: Number of accounts deleted
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        try:
            # Find unverified accounts older than cutoff date
            unverified_users = self.db.query(User).filter(
                and_(
                    User.is_verified == False,
                    User.created_at < cutoff_date
                )
            ).all()

            count = len(unverified_users)

            if count == 0:
                logger.info("No unverified accounts to clean up")
                return 0

            # One transaction per user: batching them meant a single
            # constraint failure rolled back every deletion in the run.
            deleted = 0
            for user in unverified_users:
                logger.info(f"Deleting unverified account: {_mask(user.email)} (created: {user.created_at})")
                try:
                    self.db.delete(user)
                    self.db.commit()
                    deleted += 1
                except Exception as e:
                    self.db.rollback()
                    logger.error(f"Could not delete account {_mask(user.email)}: {e}")

            logger.info(f"Deleted {deleted}/{count} unverified accounts older than {days} days")
            return deleted

        except Exception as e:
            logger.error(f"Error cleaning up unverified accounts: {e}")
            self.db.rollback()
            return 0

    def cleanup_empty_inactive_accounts(self, days: int = 30) -> int:
        """
        Delete verified accounts with no websites that have been inactive for specified days.

        Args:
            days: Number of days of inactivity after which empty accounts are deleted (default: 30)

        Returns:
            int: Number of accounts deleted
        """
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        try:
            # Find verified users with no websites and no recent sessions
            users_with_no_websites = self.db.query(User).outerjoin(Website).filter(
                and_(
                    User.is_verified == True,
                    Website.id == None  # No websites
                )
            ).all()

            deleted_count = 0

            for user in users_with_no_websites:
                # Check if user has any session activity in the last X days
                recent_session = self.db.query(UserSession).filter(
                    and_(
                        UserSession.user_email == user.email,
                        UserSession.created_at >= cutoff_date
                    )
                ).first()

                # If no recent session, delete the account
                if not recent_session:
                    logger.info(f"Deleting inactive empty account: {_mask(user.email)} (created: {user.created_at})")
                    # One transaction per user (see cleanup_unverified_accounts)
                    try:
                        self.db.delete(user)
                        self.db.commit()
                        deleted_count += 1
                    except Exception as e:
                        self.db.rollback()
                        logger.error(f"Could not delete account {_mask(user.email)}: {e}")

            if deleted_count > 0:
                logger.info(f"Deleted {deleted_count} empty inactive accounts (no activity for {days} days)")
            else:
                logger.info("No empty inactive accounts to clean up")

            return deleted_count

        except Exception as e:
            logger.error(f"Error cleaning up empty inactive accounts: {e}")
            self.db.rollback()
            return 0

    def cleanup_expired_sessions(self) -> int:
        """
        Delete expired sessions from database.

        Returns:
            int: Number of sessions deleted
        """
        try:
            now = datetime.now(timezone.utc)

            # Count expired sessions
            count = self.db.query(UserSession).filter(
                UserSession.expires_at < now
            ).delete(synchronize_session=False)

            self.db.commit()

            if count > 0:
                logger.info(f"Deleted {count} expired sessions")
            else:
                logger.info("No expired sessions to clean up")

            return count

        except Exception as e:
            logger.error(f"Error cleaning up expired sessions: {e}")
            self.db.rollback()
            return 0

    def purge_old_event_data(self) -> int:
        """
        Data retention: delete analytics events older than DATA_RETENTION_DAYS.

        Off by default (0 = keep forever — the self-hoster's data, their call).
        When enabled it prunes every event table, plus email_logs on their own
        shorter clock (EMAIL_LOG_RETENTION_DAYS) since those rows contain
        recipient addresses and have no analytics value.
        """
        from sqlalchemy import text
        from app.config import settings

        total = 0
        now = datetime.now(timezone.utc)

        try:
            if settings.DATA_RETENTION_DAYS > 0:
                cutoff = now - timedelta(days=settings.DATA_RETENTION_DAYS)
                for table, ts_col in [
                    ("pageviews", "timestamp"),
                    ("custom_events", "timestamp"),
                    ("ecommerce_events", "timestamp"),
                    ("goal_conversions", "timestamp"),
                    ("funnel_events", "timestamp"),
                    ("revenue_transactions", "timestamp"),
                ]:
                    result = self.db.execute(
                        text(f"DELETE FROM {table} WHERE {ts_col} < :cutoff"),  # nosec: table names are a fixed allowlist above
                        {"cutoff": cutoff},
                    )
                    if result.rowcount:
                        logger.info(f"Retention: deleted {result.rowcount} rows from {table} (older than {settings.DATA_RETENTION_DAYS}d)")
                        total += result.rowcount
                self.db.commit()

            # Email logs always age out (they hold recipient addresses)
            email_cutoff = now - timedelta(days=settings.EMAIL_LOG_RETENTION_DAYS)
            result = self.db.execute(
                text("DELETE FROM email_logs WHERE sent_at < :cutoff"), {"cutoff": email_cutoff}
            )
            if result.rowcount:
                logger.info(f"Retention: deleted {result.rowcount} email_logs older than {settings.EMAIL_LOG_RETENTION_DAYS}d")
                total += result.rowcount
            self.db.commit()

            return total

        except Exception as e:
            logger.error(f"Error purging old event data: {e}")
            self.db.rollback()
            return total

    def run_all_cleanup_tasks(self) -> Tuple[int, int, int, int]:
        """
        Run all cleanup tasks.

        Returns:
            Tuple: (unverified_deleted, empty_inactive_deleted, sessions_deleted, retention_deleted)
        """
        logger.info("=" * 80)
        logger.info("RUNNING CLEANUP TASKS")
        logger.info("=" * 80)

        unverified = self.cleanup_unverified_accounts(days=7)
        empty_inactive = self.cleanup_empty_inactive_accounts(days=30)
        sessions = self.cleanup_expired_sessions()
        retained = self.purge_old_event_data()

        logger.info("=" * 80)
        logger.info(f"CLEANUP COMPLETE - Deleted: {unverified} unverified, {empty_inactive} inactive, {sessions} sessions, {retained} retention rows")
        logger.info("=" * 80)

        return (unverified, empty_inactive, sessions, retained)


def run_daily_cleanup():
    """Run daily cleanup tasks (intended for scheduled jobs)."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        service = CleanupService(db)
        service.run_all_cleanup_tasks()
    finally:
        db.close()


if __name__ == "__main__":
    # Allow running cleanup manually
    run_daily_cleanup()
