"""
SQLAlchemy models package.

All models are imported here for easy access and to ensure they're
registered with SQLAlchemy's metadata. IMPORTANT: every model module must be
imported here — Base.metadata (used by create_all and Alembic) only knows
about tables whose modules have been imported.
"""
from app.models.user import User
from app.models.session import Session
from app.models.website import Website
from app.models.pageview import Pageview
from app.models.custom_event import CustomEvent
from app.models.goal import Goal, GoalConversion
from app.models.funnel import Funnel, FunnelEvent
from app.models.api_token import ApiToken
from app.models.alert_settings import AlertSettings
from app.models.website_member import WebsiteMember, MemberRole, MemberStatus
from app.models.ecommerce_event import EcommerceEvent
from app.models.used_magic_token import UsedMagicToken
from app.models.email_log import EmailLog
from app.models.job_run import JobRun

__all__ = [
    "User",
    "JobRun",
    "Session",
    "Website",
    "Pageview",
    "CustomEvent",
    "Goal",
    "GoalConversion",
    "Funnel",
    "FunnelEvent",
    "ApiToken",
    "AlertSettings",
    "WebsiteMember",
    "MemberRole",
    "MemberStatus",
    "EcommerceEvent",
    "UsedMagicToken",
    "EmailLog",
]
