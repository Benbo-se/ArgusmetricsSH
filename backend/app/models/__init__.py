"""
SQLAlchemy models package.

All models are imported here for easy access and to ensure they're
registered with SQLAlchemy's metadata.
"""
from app.models.user import User
from app.models.session import Session
from app.models.website import Website
from app.models.pageview import Pageview
from app.models.goal import Goal, GoalConversion
from app.models.api_token import ApiToken
from app.models.alert_settings import AlertSettings
from app.models.website_member import WebsiteMember, MemberRole, MemberStatus
from app.models.ecommerce_event import EcommerceEvent
from app.models.revenue_transaction import RevenueTransaction
from app.models.used_magic_token import UsedMagicToken
from app.models.processed_stripe_event import ProcessedStripeEvent

__all__ = [
    "User",
    "Session",
    "Website",
    "Pageview",
    "Goal",
    "GoalConversion",
    "ApiToken",
    "AlertSettings",
    "WebsiteMember",
    "MemberRole",
    "MemberStatus",
    "EcommerceEvent",
    "RevenueTransaction",
    "UsedMagicToken",
    "ProcessedStripeEvent",
]
