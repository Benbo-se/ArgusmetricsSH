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


    def _is_hypertable(self, table: str) -> bool:
        """Whether this table is partitioned by TimescaleDB.

        Asked of the database rather than kept in a list, so a table converted
        later is handled without anyone remembering to update this file. The
        answer decides which delete is safe, so getting it wrong by omission
        would be a silent data-loss bug.
        """
        from sqlalchemy import text

        return bool(
            self.db.execute(
                text(
                    "SELECT 1 FROM timescaledb_information.hypertables "
                    " WHERE hypertable_name = :t"
                ),
                {"t": table},
            ).scalar()
        )

    def _drop_whole_chunks(self, table: str, cutoff) -> int:
        """Drop chunks that lie entirely before the cutoff.

        drop_chunks only takes chunks whose every row is older than the
        cutoff, so it never removes anything that should be kept. It also
        never removes everything that should go: the chunk straddling the
        cutoff holds a mix, and its old rows are deleted by the batched pass
        that follows. Both are needed, and in that order.

        Returns an estimate rather than a count, because dropping a chunk does
        not visit its rows. Counting them first would undo the point.
        """
        from sqlalchemy import text

        chunks = self.db.execute(
            text("SELECT show_chunks(:t, older_than => :cutoff)::text"),
            {"t": table, "cutoff": cutoff},
        ).scalars().all()

        if not chunks:
            return 0

        approximate = self.db.execute(
            text(
                # greatest(...,0) because reltuples is -1 on a relation that
                # has never been analysed, which every freshly created chunk
                # is. A negative estimate would then be reported as a negative
                # number of deleted rows.
                "SELECT coalesce(sum(greatest(c.reltuples, 0)), 0)::bigint "
                "  FROM unnest(cast(:names as text[])) n "
                "  JOIN pg_class c ON c.oid = n::regclass"
            ),
            {"names": chunks},
        ).scalar() or 0

        self.db.execute(
            text("SELECT drop_chunks(:t, older_than => :cutoff)"),
            {"t": table, "cutoff": cutoff},
        )
        self.db.commit()

        logger.info(
            f"Retention: dropped {len(chunks)} chunks from {table} "
            f"(about {approximate} rows), older than {cutoff.date()}"
        )
        return int(approximate)

    def _purge_in_batches(self, table: str, ts_col: str, cutoff) -> int:
        """Delete everything older than the cutoff, a batch at a time.

        A single `DELETE FROM pageviews WHERE timestamp < cutoff` is fine on a
        table that is already trimmed and dangerous on one that is not. The
        first run after retention is switched on is exactly the second case:
        one long transaction over every row the product has ever recorded,
        holding locks and generating write-ahead log the whole time, while the
        tracking endpoints are trying to insert into the same table.

        Batching keeps each transaction short. A run that does not finish
        leaves the rest for tomorrow, which is the right trade for a nightly
        job: falling behind is recoverable, blocking ingestion is not.

        On a hypertable most of the work is not a delete at all. Whole chunks
        that lie entirely before the cutoff are dropped, which is a file
        deletion rather than a scan, and only the chunk straddling the cutoff
        has rows deleted one batch at a time.

        Batching is by primary key, never by ctid. A ctid is a location inside
        one physical relation, and a hypertable is many relations, so
        `DELETE ... WHERE ctid IN (SELECT ctid ...)` matches the same location
        in every chunk. Measured on this database: with exactly one row old
        enough to purge, that statement deleted seven rows, six of them
        current. Plain tables keep the ctid form, where it is both correct and
        cheaper.
        """
        from sqlalchemy import text

        from app.config import settings

        batch = max(1, settings.RETENTION_BATCH_SIZE)
        ceiling = settings.RETENTION_MAX_ROWS_PER_RUN
        deleted = 0

        # Counted separately, and deliberately not against the ceiling. The
        # ceiling exists to bound an expensive scan-and-delete on the first run
        # over a large table; dropping a chunk is a file deletion whose cost
        # does not depend on how many rows were in it. Charging dropped rows
        # against the ceiling would let one dropped chunk exhaust the budget
        # and leave the boundary rows untouched every night, forever.
        dropped = 0
        if self._is_hypertable(table):
            dropped = self._drop_whole_chunks(table, cutoff)

        while True:
            if ceiling and deleted >= ceiling:
                logger.warning(
                    f"Retention: stopped at {deleted} rows from {table}, the "
                    f"per-run ceiling. The rest goes tomorrow."
                )
                break

            size = batch if not ceiling else min(batch, ceiling - deleted)

            if self._is_hypertable(table):
                # (id, timestamp) is the primary key on every hypertable here,
                # and unlike ctid it identifies a row across all chunks.
                statement = (
                    f"DELETE FROM {table} WHERE (id, {ts_col}) IN ("
                    f"  SELECT id, {ts_col} FROM {table}"
                    f"   WHERE {ts_col} < :cutoff LIMIT :size)"
                )
            else:
                statement = (
                    f"DELETE FROM {table} WHERE ctid IN ("
                    f"  SELECT ctid FROM {table} WHERE {ts_col} < :cutoff LIMIT :size)"
                )

            result = self.db.execute(
                text(statement),  # nosec: table and column come from a fixed allowlist
                {"cutoff": cutoff, "size": size},
            )
            self.db.commit()

            if not result.rowcount:
                break
            deleted += result.rowcount

        if deleted:
            logger.info(
                f"Retention: deleted {deleted} rows from {table} "
                f"(older than {settings.DATA_RETENTION_DAYS}d)"
            )
        return dropped + deleted

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
                    # The transaction claims age out with the events they
                    # protect. Left alone they would be the one table that
                    # grows forever, and a claim outliving its purchase
                    # protects nothing.
                    ("ecommerce_transactions", "first_seen"),
                    ("goal_conversions", "timestamp"),
                    ("funnel_events", "timestamp"),
                ]:
                    total += self._purge_in_batches(table, ts_col, cutoff)

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
    from app.database import SessionLocal, set_rls_context

    db = SessionLocal()
    # Retention purges span every tenant, so this runs as a job rather than as
    # any one user. Stated explicitly so it is never mistaken for a missing
    # context once policies are in place.
    set_rls_context(db, context="job")
    try:
        service = CleanupService(db)
        service.run_all_cleanup_tasks()
    finally:
        db.close()


if __name__ == "__main__":
    # Allow running cleanup manually
    run_daily_cleanup()
