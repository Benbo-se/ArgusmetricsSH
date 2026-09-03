"""
Website service for managing website tracking configuration.

Handles the business logic for:
- Creating websites with unique tracking codes
- Listing user's websites
- Retrieving website details
- Updating website information
- Deleting websites
"""
import logging
import secrets
import string
from typing import Optional, List, Dict
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text

from app.models.website import Website
from app.config import settings

logger = logging.getLogger(__name__)


class WebsiteService:
    """
    Service for handling website management operations.

    This service manages website tracking configuration:
    1. Create websites with unique tracking codes
    2. Validate domain uniqueness
    3. Ensure user ownership for all operations
    4. List, retrieve, update, and delete websites

    Attributes:
        db: SQLAlchemy database session
    """

    def __init__(self, db: Session):
        """
        Initialize website service with database session.

        Args:
            db: SQLAlchemy database session for database operations
        """
        self.db = db
        logger.debug("WebsiteService initialized")

    def _generate_tracking_code(self, length: int = 8) -> str:
        """
        Generate a unique alphanumeric tracking code.

        Creates a random tracking code and ensures it's unique in the database.
        If a collision occurs, generates a new one until unique.

        Args:
            length: Length of tracking code (default: 8)

        Returns:
            str: Unique alphanumeric tracking code

        Example:
            code = self._generate_tracking_code()
            # Returns: "a1b2c3d4"
        """
        max_attempts = 10
        for attempt in range(max_attempts):
            # Generate random alphanumeric string
            alphabet = string.ascii_lowercase + string.digits
            tracking_code = ''.join(secrets.choice(alphabet) for _ in range(length))

            # Check if it's unique
            existing = self.db.query(Website).filter(
                Website.tracking_code == tracking_code
            ).first()

            if not existing:
                logger.debug(f"Generated unique tracking code: {tracking_code}")
                return tracking_code

            logger.debug(f"Tracking code collision on attempt {attempt + 1}, regenerating...")

        # If we still haven't found a unique code, use a longer one
        logger.warning(f"Failed to generate unique {length}-char tracking code after {max_attempts} attempts, using longer code")
        return self._generate_tracking_code(length=length + 2)

    def create_website(self, user_email: str, name: str, domain: str) -> Website:
        """
        Create a new website for a user.

        Generates a unique tracking code, validates domain uniqueness,
        and creates the website record.

        Args:
            user_email: Email of the user creating the website
            name: Website name/label
            domain: Website domain URL

        Returns:
            Website: Newly created website object

        Raises:
            ValueError: If domain already exists or validation fails
            Exception: If database operation fails

        Example:
            service = WebsiteService(db)
            website = service.create_website(
                user_email="user@example.com",
                name="My Blog",
                domain="https://myblog.com"
            )
            print(f"Tracking code: {website.tracking_code}")
        """
        logger.info(f"Creating website for user: {user_email}, domain: {domain}")

        try:
            # Check if domain already exists
            existing_website = self.db.query(Website).filter(
                Website.domain == domain
            ).first()

            if existing_website:
                # Generic message: don't confirm to other tenants that a given
                # domain is tracked on this instance.
                logger.warning(f"Domain already exists: {domain}")
                raise ValueError("This domain cannot be added. If you own it and believe this is an error, contact the instance administrator.")

            # Generate unique tracking code
            tracking_code = self._generate_tracking_code()

            # Generate unique verification token for DNS verification
            import secrets
            verification_token = secrets.token_urlsafe(32)  # 43 characters base64url

            # Create website
            website = Website(
                name=name,
                domain=domain,
                user_email=user_email,
                tracking_code=tracking_code,
                verification_token=verification_token,
                # Auto-verify only in local dev. (An earlier E2E shortcut
                # keyed on the mere PRESENCE of E2E_TEST_SECRET — config-
                # presence gating, the exact pattern auth's _e2e_secret_ok
                # exists to prevent. E2E suites verify via DNS mocks instead.)
                is_verified=settings.DEBUG and not settings.is_production,
                is_active=True
            )

            self.db.add(website)
            self.db.flush()  # Get website.id before creating member

            # Auto-create OWNER membership for the creator
            from app.models.website_member import WebsiteMember, MemberRole, MemberStatus
            owner_member = WebsiteMember(
                website_id=website.id,
                user_email=user_email,
                role=MemberRole.OWNER,
                status=MemberStatus.ACTIVE,
                invited_by=user_email,
            )
            self.db.add(owner_member)

            self.db.commit()
            self.db.refresh(website)

            logger.info(f"Website created successfully: {website.id} ({domain})")
            return website

        except ValueError:
            # Re-raise ValueError for domain validation
            raise

        except IntegrityError as e:
            self.db.rollback()
            logger.error(f"Database integrity error creating website: {e}")
            raise ValueError("Domain is already registered or invalid data provided")

        except Exception as e:
            self.db.rollback()
            logger.error(f"Unexpected error creating website: {e}", exc_info=True)
            raise

    def get_user_websites(self, user_email: str) -> List[Website]:
        """
        Get all websites accessible to a user.

        Retrieves all websites owned by the user OR where the user is an active team member,
        ordered by creation date (newest first).

        Args:
            user_email: Email of the user

        Returns:
            List[Website]: List of accessible websites

        Example:
            service = WebsiteService(db)
            websites = service.get_user_websites("user@example.com")
            print(f"User has access to {len(websites)} websites")
        """
        logger.info(f"Retrieving websites for user: {user_email}")

        try:
            from app.models.website_member import WebsiteMember, MemberStatus

            # Get owned websites
            owned_websites = self.db.query(Website).filter(
                Website.user_email == user_email
            ).all()

            # Get website IDs where user is an active team member
            team_website_ids = self.db.query(WebsiteMember.website_id).filter(
                WebsiteMember.user_email == user_email,
                WebsiteMember.status == MemberStatus.ACTIVE
            ).all()

            # Extract website IDs
            team_ids = [wid[0] for wid in team_website_ids]

            # Get team websites
            team_websites = []
            if team_ids:
                team_websites = self.db.query(Website).filter(
                    Website.id.in_(team_ids)
                ).all()

            # Combine and deduplicate (shouldn't be duplicates, but just in case)
            all_websites = owned_websites + team_websites
            website_dict = {w.id: w for w in all_websites}
            websites = list(website_dict.values())

            # Sort by created_at descending
            websites.sort(key=lambda w: w.created_at, reverse=True)

            logger.debug(f"Found {len(websites)} websites for user: {user_email} ({len(owned_websites)} owned, {len(team_websites)} team)")
            return websites

        except Exception as e:
            logger.error(f"Error retrieving websites for {user_email}: {e}", exc_info=True)
            return []

    def get_website_by_id(self, website_id: int, user_email: str) -> Optional[Website]:
        """
        Get a specific website by ID with access verification.

        Retrieves a website if the user owns it OR is a team member with access.

        Args:
            website_id: ID of the website to retrieve
            user_email: Email of the user (for access verification)

        Returns:
            Website: Website object if found and user has access, None otherwise

        Example:
            service = WebsiteService(db)
            website = service.get_website_by_id(1, "user@example.com")
            if website:
                print(f"Website: {website.name}")
            else:
                print("Website not found or access denied")
        """
        logger.info(f"Retrieving website {website_id} for user: {user_email}")

        try:
            # First check if user owns the website
            website = self.db.query(Website).filter(
                Website.id == website_id,
                Website.user_email == user_email
            ).first()

            if website:
                logger.debug(f"Website found (owner): {website.id} ({website.domain})")
                return website

            # If not owner, check if user is a team member with active status
            from app.models.website_member import WebsiteMember, MemberStatus

            member = self.db.query(WebsiteMember).filter(
                WebsiteMember.website_id == website_id,
                WebsiteMember.user_email == user_email,
                WebsiteMember.status == MemberStatus.ACTIVE
            ).first()

            if member:
                # User is a team member, get the website
                website = self.db.query(Website).filter(Website.id == website_id).first()
                if website:
                    logger.debug(f"Website found (team member): {website.id} ({website.domain})")
                    return website

            logger.debug(f"Website {website_id} not found or no access for user {user_email}")
            return None

        except Exception as e:
            logger.error(f"Error retrieving website {website_id}: {e}", exc_info=True)
            return None

    def get_website_by_tracking_code(self, tracking_code: str) -> Optional[Website]:
        """
        Get a website by its tracking code.

        Used for analytics tracking - does not verify ownership.
        Only returns active websites.

        Args:
            tracking_code: Unique tracking code

        Returns:
            Website: Website object if found and active, None otherwise

        Example:
            service = WebsiteService(db)
            website = service.get_website_by_tracking_code("a1b2c3d4")
            if website and website.is_active:
                print(f"Tracking enabled for: {website.domain}")
        """
        logger.debug(f"Retrieving website by tracking code: {tracking_code}")

        try:
            website = self.db.query(Website).filter(
                Website.tracking_code == tracking_code,
                Website.is_active == True
            ).first()

            if website:
                logger.debug(f"Website found for tracking code: {website.domain}")
            else:
                logger.debug(f"No active website found for tracking code: {tracking_code}")

            return website

        except Exception as e:
            logger.error(f"Error retrieving website by tracking code: {e}", exc_info=True)
            return None

    def update_website(
        self,
        website_id: int,
        user_email: str,
        name: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> Website:
        """
        Update a website's information.

        Updates website name and/or active status. Verifies user ownership
        before allowing updates.

        Args:
            website_id: ID of the website to update
            user_email: Email of the user (for ownership verification)
            name: New website name (optional)
            is_active: New active status (optional)

        Returns:
            Website: Updated website object

        Raises:
            ValueError: If website not found, access denied, or no updates provided
            Exception: If database operation fails

        Example:
            service = WebsiteService(db)
            website = service.update_website(
                website_id=1,
                user_email="user@example.com",
                name="My Updated Blog",
                is_active=False
            )
            print(f"Website updated: {website.name}")
        """
        logger.info(f"Updating website {website_id} for user: {user_email}")

        # Validate that at least one field is being updated
        if name is None and is_active is None:
            logger.warning("No update fields provided")
            raise ValueError("At least one field must be provided for update")

        try:
            # Get website with ownership verification
            website = self.get_website_by_id(website_id, user_email)

            if not website:
                logger.warning(f"Website {website_id} not found or access denied for user {user_email}")
                raise ValueError("Website not found or access denied")

            # Update fields
            if name is not None:
                logger.debug(f"Updating website name: {website.name} -> {name}")
                website.name = name

            if is_active is not None:
                logger.debug(f"Updating website active status: {website.is_active} -> {is_active}")
                website.is_active = is_active

            self.db.commit()
            self.db.refresh(website)

            logger.info(f"Website {website_id} updated successfully")
            return website

        except ValueError:
            # Re-raise ValueError for validation errors
            raise

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating website {website_id}: {e}", exc_info=True)
            raise

    def delete_website(self, website_id: int, user_email: str) -> bool:
        """
        Delete a website.

        Permanently deletes a website. Verifies user ownership before deletion.

        Args:
            website_id: ID of the website to delete
            user_email: Email of the user (for ownership verification)

        Returns:
            bool: True if deleted successfully, False if not found

        Raises:
            ValueError: If website not found or access denied
            Exception: If database operation fails

        Example:
            service = WebsiteService(db)
            success = service.delete_website(1, "user@example.com")
            if success:
                print("Website deleted successfully")
        """
        logger.info(f"Deleting website {website_id} for user: {user_email}")

        try:
            # Get website with ownership verification
            website = self.get_website_by_id(website_id, user_email)

            if not website:
                logger.warning(f"Website {website_id} not found or access denied for user {user_email}")
                raise ValueError("Website not found or access denied")

            domain = website.domain
            self.db.delete(website)
            self.db.commit()

            logger.info(f"Website {website_id} ({domain}) deleted successfully")
            return True

        except ValueError:
            # Re-raise ValueError for validation errors
            raise

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error deleting website {website_id}: {e}", exc_info=True)
            raise

    def update_email_reports_config(
        self,
        website_id: int,
        user_email: str,
        enabled: bool,
        frequency: Optional[str] = None,
        recipient: Optional[str] = None,
        day: Optional[int] = None
    ) -> Website:
        """
        Update email reports configuration for a website.

        Args:
            website_id: ID of the website to update
            user_email: Email of the user (for ownership verification)
            enabled: Whether email reports are enabled
            frequency: Report frequency ('weekly' or 'monthly')
            recipient: Email address to send reports to
            day: Day for sending (1-7 for weekly, 1-31 for monthly)

        Returns:
            Website: Updated website object

        Raises:
            ValueError: If website not found, access denied, or invalid configuration
            Exception: If database operation fails

        Example:
            service = WebsiteService(db)
            website = service.update_email_reports_config(
                website_id=1,
                user_email="user@example.com",
                enabled=True,
                frequency="weekly",
                recipient="user@example.com",
                day=1
            )
        """
        logger.info(f"Updating email reports config for website {website_id}")

        try:
            # Get website with ownership verification
            website = self.get_website_by_id(website_id, user_email)

            if not website:
                logger.warning(f"Website {website_id} not found or access denied for user {user_email}")
                raise ValueError("Website not found or access denied")

            # Update email reports configuration
            website.email_reports_enabled = enabled

            if enabled:
                # Validate required fields when enabling
                if not frequency or not recipient or day is None:
                    raise ValueError("Frequency, recipient, and day are required when enabling email reports")

                # Validate frequency
                if frequency not in ['weekly', 'monthly']:
                    raise ValueError("Frequency must be 'weekly' or 'monthly'")

                # Validate day based on frequency
                if frequency == 'weekly' and not (1 <= day <= 7):
                    raise ValueError("Day must be between 1-7 for weekly reports (1=Monday, 7=Sunday)")
                elif frequency == 'monthly' and not (1 <= day <= 31):
                    raise ValueError("Day must be between 1-31 for monthly reports")

                website.email_reports_frequency = frequency
                website.email_reports_recipient = recipient
                website.email_reports_day = day

                logger.info(f"Email reports enabled for website {website_id}: {frequency} on day {day} to {recipient}")
            else:
                # When disabling, clear the config but don't require them
                website.email_reports_frequency = frequency
                website.email_reports_recipient = recipient
                website.email_reports_day = day
                logger.info(f"Email reports disabled for website {website_id}")

            self.db.commit()
            self.db.refresh(website)

            return website

        except ValueError:
            # Re-raise ValueError for validation errors
            raise

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error updating email reports config for website {website_id}: {e}", exc_info=True)
            raise

    def get_monthly_pageviews(self, website_ids: List[int]) -> int:
        """Get total pageview count for the current month across given websites."""
        if not website_ids:
            return 0

        try:
            now = datetime.now(timezone.utc)
            month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

            result = self.db.execute(text("""
                SELECT COUNT(*)
                FROM pageviews
                WHERE website_id = ANY(:website_ids)
                AND timestamp >= :month_start
            """), {
                "website_ids": website_ids,
                "month_start": month_start
            })
            return result.scalar() or 0

        except Exception as e:
            logger.error(f"Error getting monthly pageviews: {e}", exc_info=True)
            return 0

    def get_public_website(self, share_token: str) -> Optional[Website]:
        """Get a publicly shared website by its share token."""
        try:
            return self.db.query(Website).filter(
                Website.public_share_token == share_token,
                Website.is_public == True
            ).first()
        except Exception as e:
            logger.error(f"Error getting public website: {e}", exc_info=True)
            return None

    def get_funnels(self, website_id: int) -> List:
        """Get all active funnels for a website."""
        try:
            from app.models.funnel import Funnel
            return self.db.query(Funnel).filter(
                Funnel.website_id == website_id,
                Funnel.is_active == True
            ).all()
        except Exception as e:
            logger.error(f"Error getting funnels: {e}", exc_info=True)
            return []

    def mark_verified(self, website_id: int) -> Website:
        """Mark a website as domain-verified."""
        website = self.db.query(Website).filter(Website.id == website_id).first()
        if not website:
            raise ValueError(f"Website {website_id} not found")

        website.is_verified = True
        website.verified_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(website)
        return website

    def toggle_public_share(self, website_id: int, is_public: bool) -> Website:
        """Enable or disable public dashboard sharing."""
        import secrets as _secrets

        website = self.db.query(Website).filter(Website.id == website_id).first()
        if not website:
            raise ValueError(f"Website {website_id} not found")

        website.is_public = is_public

        if is_public and not website.public_share_token:
            website.public_share_token = _secrets.token_urlsafe(24)[:32]

        self.db.commit()
        self.db.refresh(website)
        return website
