"""
User model for authentication and account management.
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.sql import func
from app.database import Base


class User(Base):
    """
    User model for storing user account information.

    Attributes:
        id: Primary key
        email: User's email address (unique, indexed)
        is_verified: Whether the user has verified their email
        created_at: Timestamp when user was created
        updated_at: Timestamp when user was last updated
        trial_expires: When 14-day trial expires
        plan: Subscription plan ('free', 'pro', 'business')
        subscription_status: Status ('trial', 'active', 'cancelled', 'expired')
        monthly_pageviews_used: Pageview counter for current month
        monthly_reset_date: When counter resets (first day of next month)
        stripe_customer_id: Stripe customer ID
        stripe_subscription_id: Stripe subscription ID
    """

    __tablename__ = "users"

    # Core fields
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Trial and billing fields
    trial_expires = Column(DateTime(timezone=True), nullable=True)
    plan = Column(String(50), default='free')  # 'free', 'starter', 'pro', 'business'
    subscription_status = Column(String(50), default='trial')  # 'trial', 'active', 'cancelled', 'expired'
    monthly_pageviews_used = Column(Integer, default=0)
    monthly_reset_date = Column(DateTime(timezone=True), nullable=True)
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_subscription_id = Column(String(255), nullable=True)

    # AI quota fields
    ai_chatbot_quota = Column(Integer, default=0)  # Monthly AI chatbot message quota
    ai_chatbot_used_this_month = Column(Integer, default=0)  # AI messages used this month
    ai_quota_reset_date = Column(DateTime(timezone=True), nullable=True)  # Next quota reset date

    def __repr__(self) -> str:
        return f"<User(email='{self.email}', verified={self.is_verified}, plan='{self.plan}', status='{self.subscription_status}')>"
