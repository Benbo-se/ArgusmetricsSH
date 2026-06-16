"""
Billing middleware for trial enforcement and view limits.
"""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from app.models.user import User


def get_next_month_start(from_date: datetime = None) -> datetime:
    """
    Get first day of next month.

    Args:
        from_date: Reference date (defaults to now)

    Returns:
        Datetime of first day of next month
    """
    if from_date is None:
        from_date = datetime.now(timezone.utc)

    if from_date.month == 12:
        return datetime(from_date.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        return datetime(from_date.year, from_date.month + 1, 1, tzinfo=timezone.utc)


async def check_trial_and_limits(user: User, db: Session) -> None:
    """
    Enforce trial expiration and monthly view limits.

    Args:
        user: User object to check
        db: Database session

    Raises:
        HTTPException 402: Trial expired without active subscription
        HTTPException 429: Monthly pageview limit reached (free plan only)
    """
    now = datetime.now(timezone.utc)

    # Check trial expiration
    if user.trial_expires and now > user.trial_expires:
        if user.subscription_status != 'active':
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=(
                    f"Your 14-day trial has expired. "
                    f"Please upgrade to continue using Argusmetrics."
                ),
                headers={"X-Trial-Expired": "true"}
            )

    # Check monthly view limits for free plan
    if user.plan == 'free':
        # Reset counter if new month
        if user.monthly_reset_date and now >= user.monthly_reset_date:
            user.monthly_pageviews_used = 0
            user.monthly_reset_date = get_next_month_start(now)
            db.commit()

        # Check limit
        if user.monthly_pageviews_used >= 10000:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Monthly pageview limit reached "
                    f"({user.monthly_pageviews_used:,}/10,000). "
                    f"Upgrade to Pro for unlimited views."
                ),
                headers={
                    "X-Limit-Reached": "true",
                    "X-Limit-Used": str(user.monthly_pageviews_used),
                    "X-Limit-Max": "10000"
                }
            )


def increment_pageview_counter(user_email: str, db: Session) -> None:
    """
    Increment user's monthly pageview counter.

    Args:
        user_email: Email of user to increment
        db: Database session
    """
    user = db.query(User).filter(User.email == user_email).first()
    if user and user.plan == 'free':
        # Only count pageviews for free plan users
        user.monthly_pageviews_used += 1
        db.commit()
