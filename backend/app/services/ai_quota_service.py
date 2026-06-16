"""
AI Quota Service for managing AI feature usage limits.

Provides functions for:
- Checking if user has available AI quota
- Incrementing AI usage counters
- Resetting monthly quotas
- Getting quota information
"""
import logging
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta
from typing import Dict, Optional
from sqlalchemy.orm import Session

from app.models.user import User

logger = logging.getLogger(__name__)

# AI quota limits by plan (messages per month)
AI_QUOTA_LIMITS = {
    'free': 0,        # Free tier has no AI access
    'starter': 50,    # Starter: 50 messages/month
    'pro': 1000,      # Pro: 1,000 messages/month
    'business': 10000 # Business: 10,000 messages/month
}


def get_plan_quota(plan: str) -> int:
    """
    Get the AI quota limit for a given plan.

    Args:
        plan: Subscription plan name

    Returns:
        int: Monthly AI message quota
    """
    return AI_QUOTA_LIMITS.get(plan, 0)


def initialize_user_quota(db: Session, user: User) -> None:
    """
    Initialize AI quota for a user based on their plan.
    Sets quota and reset date if not already set.

    Args:
        db: Database session
        user: User object
    """
    if user.ai_chatbot_quota is None or user.ai_chatbot_quota == 0:
        user.ai_chatbot_quota = get_plan_quota(user.plan)
        user.ai_chatbot_used_this_month = 0

        # Set reset date to first day of next month
        now = datetime.now(timezone.utc)
        user.ai_quota_reset_date = (now + relativedelta(months=1)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

        db.commit()
        logger.info(f"Initialized AI quota for user {user.email}: {user.ai_chatbot_quota} messages")


def check_and_reset_quota_if_needed(db: Session, user: User) -> None:
    """
    Check if quota needs to be reset and reset it if needed.
    Resets on the first day of each month.

    Args:
        db: Database session
        user: User object
    """
    now = datetime.now(timezone.utc)

    # If reset date is None or has passed, reset the quota
    if user.ai_quota_reset_date is None or now >= user.ai_quota_reset_date:
        user.ai_chatbot_used_this_month = 0

        # Set next reset date to first day of next month
        user.ai_quota_reset_date = (now + relativedelta(months=1)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

        db.commit()
        logger.info(f"Reset AI quota for user {user.email}. Next reset: {user.ai_quota_reset_date}")


def check_ai_quota(db: Session, user: User, feature_name: str = "chatbot") -> bool:
    """
    Check if user has available AI quota for a feature.

    Args:
        db: Database session
        user: User object
        feature_name: Name of AI feature (e.g., 'chatbot')

    Returns:
        bool: True if user has quota remaining, False otherwise
    """
    # Initialize quota if not set
    if user.ai_chatbot_quota is None:
        initialize_user_quota(db, user)

    # Check if quota needs reset
    check_and_reset_quota_if_needed(db, user)

    # Refresh user object to get updated values
    db.refresh(user)

    # Check if user has quota remaining
    has_quota = user.ai_chatbot_used_this_month < user.ai_chatbot_quota

    if not has_quota:
        logger.warning(
            f"User {user.email} exceeded AI quota: "
            f"{user.ai_chatbot_used_this_month}/{user.ai_chatbot_quota}"
        )

    return has_quota


def increment_ai_usage(db: Session, user: User, feature_name: str = "chatbot") -> None:
    """
    Increment AI usage counter for a user.

    Args:
        db: Database session
        user: User object
        feature_name: Name of AI feature (e.g., 'chatbot')
    """
    user.ai_chatbot_used_this_month += 1
    db.commit()

    logger.info(
        f"Incremented AI usage for {user.email}: "
        f"{user.ai_chatbot_used_this_month}/{user.ai_chatbot_quota}"
    )


def get_quota_info(user: User) -> Dict:
    """
    Get quota information for a user.

    Args:
        user: User object

    Returns:
        dict: Quota information including usage, limits, and reset date
    """
    quota = user.ai_chatbot_quota or 0
    used = user.ai_chatbot_used_this_month or 0
    remaining = max(0, quota - used)

    return {
        "plan": user.plan,
        "quota": quota,
        "used": used,
        "remaining": remaining,
        "reset_date": user.ai_quota_reset_date.isoformat() if user.ai_quota_reset_date else None,
        "has_access": quota > 0,
        "is_exceeded": used >= quota
    }


def check_ai_quota_available(user: User, amount: int = 1) -> bool:
    """Check if user has AI quota available (without DB session)."""
    if user.plan == 'free':
        return False
    used = user.ai_chatbot_used_this_month or 0
    quota = user.ai_chatbot_quota or 0
    return (quota - used) >= amount


def consume_ai_quota(user: User, amount: int = 1) -> bool:
    """Consume AI quota. Caller must db.commit()."""
    if not check_ai_quota_available(user, amount):
        logger.warning(f"AI quota exhausted for {user.email} (plan: {user.plan})")
        return False
    user.ai_chatbot_used_this_month = (user.ai_chatbot_used_this_month or 0) + amount
    logger.info(f"AI quota consumed for {user.email}: {user.ai_chatbot_used_this_month}/{user.ai_chatbot_quota}")
    return True


def update_user_ai_quota(user: User) -> None:
    """Update user's AI quota based on current plan. Caller must db.commit()."""
    new_quota = get_plan_quota(user.plan)
    if new_quota != user.ai_chatbot_quota:
        user.ai_chatbot_quota = new_quota
        logger.info(f"Updated AI quota for {user.email}: {new_quota} (plan: {user.plan})")


def get_upgrade_message(user: User) -> str:
    """
    Get appropriate upgrade message based on user's plan.

    Args:
        user: User object

    Returns:
        str: Upgrade message with recommended plan
    """
    current_plan = user.plan

    if current_plan == 'free':
        return "Upgrade to Starter (79kr/månad) for 50 AI messages per month!"
    elif current_plan == 'starter':
        return "Upgrade to Pro (199kr/månad) for 1,000 AI messages per month!"
    elif current_plan == 'pro':
        return "Upgrade to Business (499kr/månad) for 10,000 AI messages per month!"
    else:
        return "You're on the highest plan! Contact support if you need more quota."


def reset_monthly_quotas(db: Session) -> int:
    """
    Background task to reset monthly quotas for all users.
    Should be run on the first day of each month.

    Args:
        db: Database session

    Returns:
        int: Number of users whose quotas were reset
    """
    now = datetime.now(timezone.utc)

    # Find users whose reset date has passed
    users_to_reset = db.query(User).filter(
        User.ai_quota_reset_date <= now,
        User.ai_chatbot_quota > 0
    ).all()

    count = 0
    for user in users_to_reset:
        user.ai_chatbot_used_this_month = 0
        user.ai_quota_reset_date = (now + relativedelta(months=1)).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        count += 1

    db.commit()
    logger.info(f"Reset AI quotas for {count} users")

    return count


def update_quota_on_plan_change(db: Session, user: User, new_plan: str) -> None:
    """
    Update user's AI quota when their plan changes.

    Args:
        db: Database session
        user: User object
        new_plan: New subscription plan
    """
    old_quota = user.ai_chatbot_quota
    new_quota = get_plan_quota(new_plan)

    user.plan = new_plan
    user.ai_chatbot_quota = new_quota

    # Don't reset usage counter, just update quota
    # If upgrading, user gets immediate access to new quota
    # If downgrading, usage counter remains until next reset

    db.commit()
    logger.info(
        f"Updated AI quota for {user.email}: {old_quota} -> {new_quota} "
        f"(plan: {new_plan})"
    )
