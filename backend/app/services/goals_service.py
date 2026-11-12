"""
Goals service for creating, tracking, and querying goal conversions.
"""
import logging
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, distinct

from app.models.pageview import Pageview
from app.models.website import Website
from app.models.goal import Goal, GoalConversion
from app.utils.security import generate_visitor_hash
from app.services.website_lookup import resolve_tracking_code
from app.services.usage_service import LIMIT_MESSAGE, may_record

logger = logging.getLogger(__name__)


def goal_conversion_stats(
    db: Session,
    website_id: int,
    start_date: datetime,
    end_date: Optional[datetime] = None,
) -> Dict:
    """Visitors, and per goal the conversions, converters and conversion rate.

    The one definition behind every conversion rate shown: the share of the
    period's unique visitors who converted at least once. That cannot pass
    100%, where conversions divided by visitors can (one visitor ordering
    twice is two conversions). end_date None means no upper bound.

    Returns {"visitors": int, "goals": {goal_id: {"conversions", "converters",
    "rate"}}} with a rate in percent to one decimal. Goals with no
    conversions in the period are absent.
    """
    visitor_filters = [Pageview.website_id == website_id, Pageview.timestamp >= start_date]
    conversion_filters = [
        GoalConversion.website_id == website_id,
        GoalConversion.timestamp >= start_date,
    ]
    if end_date is not None:
        visitor_filters.append(Pageview.timestamp <= end_date)
        conversion_filters.append(GoalConversion.timestamp <= end_date)

    visitors = db.query(
        func.count(distinct(Pageview.visitor_hash))
    ).filter(and_(*visitor_filters)).scalar() or 0

    rows = db.query(
        GoalConversion.goal_id,
        func.count(GoalConversion.id),
        func.count(distinct(GoalConversion.visitor_hash)),
    ).filter(and_(*conversion_filters)).group_by(GoalConversion.goal_id).all()

    goals = {
        goal_id: {
            "conversions": conversions,
            "converters": converters,
            "rate": round(converters / visitors * 100, 1) if visitors else 0.0,
        }
        for goal_id, conversions, converters in rows
    }
    return {"visitors": visitors, "goals": goals}


class GoalsService:
    """Service for goal CRUD and conversion tracking."""

    def __init__(self, db: Session):
        self.db = db

    def _generate_visitor_hash(self, ip_address: str, user_agent: str, website_domain: str) -> str:
        return generate_visitor_hash(ip_address, user_agent, website_domain)

    def create_goal(
        self,
        website_id: int,
        name: str,
        event_name: str
    ) -> Optional[Goal]:
        """Create a new goal for a website."""
        logger.info(f"Creating goal: website_id={website_id}, name={name}, event={event_name}")

        try:
            existing = self.db.query(Goal).filter(
                Goal.website_id == website_id,
                Goal.event_name == event_name
            ).first()

            if existing:
                logger.warning(f"Goal with event_name '{event_name}' already exists")
                return None

            goal = Goal(
                website_id=website_id,
                name=name,
                event_name=event_name
            )

            self.db.add(goal)
            self.db.commit()
            self.db.refresh(goal)

            logger.info(f"Goal created: id={goal.id}, name={name}")
            return goal

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error creating goal: {e}", exc_info=True)
            return None

    def record_goal_conversion(
        self,
        tracking_code: str,
        event_name: str,
        ip_address: str,
        user_agent: str
    ) -> Tuple[bool, str]:
        """Record a goal conversion event."""
        logger.info(f"Recording goal conversion: tracking_code={tracking_code}, event={event_name}")

        try:
            # Resolved through a SECURITY DEFINER function, so the tracking
            # context needs no read access to websites at all. See
            # app/services/website_lookup.py.
            website = resolve_tracking_code(self.db, tracking_code)
            if website and not website.is_active:
                website = None

            if not website:
                logger.warning(f"Invalid tracking code: {tracking_code}")
                return False, "Invalid tracking code"


            # Per-account monthly limit. Checked after resolving so an invalid
            # code and a full account are reported differently, and before
            # writing so a refused event costs nothing.
            if not may_record(self.db, website.owner_email):
                return False, LIMIT_MESSAGE

            if not website.is_verified:
                logger.warning(
                    f"Domain not verified for website {website.id} ({website.domain}). "
                    f"Blocking goal conversion until owner verifies DNS record."
                )
                return False, "Domain not verified"

            visitor_hash = self._generate_visitor_hash(ip_address, user_agent, website.domain)

            goal = self.db.query(Goal).filter(
                Goal.website_id == website.id,
                Goal.event_name == event_name
            ).first()

            if not goal:
                logger.warning(f"Goal not found: event_name={event_name}")
                return False, "Goal not found"

            conversion = GoalConversion(
                goal_id=goal.id,
                website_id=website.id,
                visitor_hash=visitor_hash,
                timestamp=datetime.now(timezone.utc)
            )

            self.db.add(conversion)
            self.db.commit()

            logger.info(f"Goal conversion recorded: goal_id={goal.id}, event={event_name}")
            return True, "Conversion recorded"

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error recording goal conversion: {e}", exc_info=True)
            return False, "Failed to record conversion"

    def get_goal_stats(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> Dict:
        """Get goal statistics for a website."""
        logger.info(f"Getting goal stats: website_id={website_id}")

        try:
            goals = self.db.query(Goal).filter(
                Goal.website_id == website_id
            ).all()

            shared = goal_conversion_stats(self.db, website_id, start_date, end_date)
            total_visitors = shared["visitors"]
            quiet = {"conversions": 0, "converters": 0, "rate": 0.0}

            goal_stats = []

            for goal in goals:
                row = shared["goals"].get(goal.id, quiet)
                goal_stats.append({
                    "goal_id": goal.id,
                    "name": goal.name,
                    "event_name": goal.event_name,
                    "conversions": row["conversions"],
                    "converters": row["converters"],
                    "conversion_rate": row["rate"],
                })

            return {
                "goals": goal_stats,
                "total_visitors": total_visitors
            }

        except Exception as e:
            logger.error(f"Error getting goal stats: {e}", exc_info=True)
            return {
                "goals": [],
                "total_visitors": 0
            }

    def get_goals_list(self, website_id: int) -> List[Goal]:
        """Get all goals for a website."""
        try:
            return self.db.query(Goal).filter(
                Goal.website_id == website_id
            ).order_by(Goal.created_at.desc()).all()
        except Exception as e:
            logger.error(f"Error getting goals list: {e}", exc_info=True)
            return []

    def delete_goal(self, goal_id: int, website_id: int) -> bool:
        """Delete a goal and its conversions."""
        try:
            goal = self.db.query(Goal).filter(
                Goal.id == goal_id,
                Goal.website_id == website_id
            ).first()

            if not goal:
                return False

            self.db.delete(goal)
            self.db.commit()
            logger.info(f"Goal deleted: id={goal_id}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error deleting goal: {e}", exc_info=True)
            return False
