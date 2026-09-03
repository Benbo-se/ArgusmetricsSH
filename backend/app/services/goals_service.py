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

logger = logging.getLogger(__name__)


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

            total_visitors = self.db.query(
                func.count(distinct(Pageview.visitor_hash))
            ).filter(
                and_(
                    Pageview.website_id == website_id,
                    Pageview.timestamp >= start_date,
                    Pageview.timestamp <= end_date
                )
            ).scalar() or 0

            goal_stats = []

            for goal in goals:
                conversions = self.db.query(
                    func.count(GoalConversion.id)
                ).filter(
                    and_(
                        GoalConversion.goal_id == goal.id,
                        GoalConversion.timestamp >= start_date,
                        GoalConversion.timestamp <= end_date
                    )
                ).scalar() or 0

                conversion_rate = 0.0
                if total_visitors > 0:
                    conversion_rate = (conversions / total_visitors) * 100

                goal_stats.append({
                    "goal_id": goal.id,
                    "name": goal.name,
                    "event_name": goal.event_name,
                    "conversions": conversions,
                    "conversion_rate": round(conversion_rate, 2)
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
