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

            # Delete each user (cascade will handle sessions)
            for user in unverified_users:
                logger.info(f"Deleting unverified account: {user.email} (created: {user.created_at})")
                self.db.delete(user)

            self.db.commit()
            logger.info(f"Deleted {count} unverified accounts older than {days} days")
            return count

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
                    logger.info(f"Deleting inactive empty account: {user.email} (created: {user.created_at})")
                    self.db.delete(user)
                    deleted_count += 1

            if deleted_count > 0:
                self.db.commit()
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

    def run_all_cleanup_tasks(self) -> Tuple[int, int, int]:
        """
        Run all cleanup tasks.

        Returns:
            Tuple[int, int, int]: (unverified_deleted, empty_inactive_deleted, sessions_deleted)
        """
        logger.info("=" * 80)
        logger.info("RUNNING CLEANUP TASKS")
        logger.info("=" * 80)

        unverified = self.cleanup_unverified_accounts(days=7)
        empty_inactive = self.cleanup_empty_inactive_accounts(days=30)
        sessions = self.cleanup_expired_sessions()

        logger.info("=" * 80)
        logger.info(f"CLEANUP COMPLETE - Deleted: {unverified} unverified, {empty_inactive} inactive, {sessions} sessions")
        logger.info("=" * 80)

        return (unverified, empty_inactive, sessions)


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
