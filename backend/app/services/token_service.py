"""
API Token service for creating and validating API tokens.

Allows users to create API tokens for programmatic access to their analytics data.
"""
import hashlib
import logging
import secrets
from typing import Optional, List, Tuple
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.api_token import ApiToken
from app.models.website import Website

logger = logging.getLogger(__name__)


class TokenService:
    """
    Service for managing API tokens.

    Handles:
    - Creating new API tokens with secure random generation
    - Validating tokens and returning associated website
    - Listing tokens for a website
    - Deleting tokens
    - Updating last_used_at timestamp
    """

    def __init__(self, db: Session):
        """
        Initialize token service with database session.

        Args:
            db: SQLAlchemy database session
        """
        self.db = db
        logger.debug("TokenService initialized")

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """Hash an API token with SHA-256. Used for storage and lookup."""
        return hashlib.sha256(raw_token.encode()).hexdigest()

    def create_token(
        self,
        website_id: int,
        name: str
    ) -> Optional[Tuple[ApiToken, str]]:
        """
        Create a new API token for a website.

        Generates a cryptographically secure random token.

        Args:
            website_id: Website ID
            name: Human-readable token name

        Returns:
            Tuple of (ApiToken object, raw token string) or None on error
            The raw token is only returned once on creation
        """
        logger.info(f"Creating API token: website_id={website_id}, name={name}")

        try:
            # Generate secure random token (64 characters URL-safe)
            raw_token = secrets.token_urlsafe(48)  # 48 bytes = 64 URL-safe chars
            token_hash = self.hash_token(raw_token)

            # Create token record (store hash, not plaintext)
            token = ApiToken(
                website_id=website_id,
                name=name,
                token=token_hash,
                created_at=datetime.utcnow()
            )

            self.db.add(token)
            self.db.commit()
            self.db.refresh(token)

            logger.info(f"API token created: id={token.id}, name={name}")
            return token, raw_token

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error creating API token: {e}", exc_info=True)
            return None

    def validate_token(self, token: str) -> Optional[Website]:
        """
        Validate an API token and return the associated website.

        Also updates the last_used_at timestamp.

        Args:
            token: The API token string

        Returns:
            Website object if token is valid, None otherwise
        """
        logger.debug("Validating API token")

        try:
            # Hash input token and look up by hash
            token_hash = self.hash_token(token)
            api_token = self.db.query(ApiToken).filter(
                ApiToken.token == token_hash
            ).first()

            if not api_token:
                logger.warning("Invalid API token")
                return None

            # Get associated website
            website = self.db.query(Website).filter(
                Website.id == api_token.website_id,
                Website.is_active == True
            ).first()

            if not website:
                logger.warning(f"Website not found or inactive for token: {api_token.id}")
                return None

            # Update last_used_at
            api_token.last_used_at = datetime.utcnow()
            self.db.commit()

            logger.debug(f"API token validated: website_id={website.id}")
            return website

        except Exception as e:
            logger.error(f"Error validating API token: {e}", exc_info=True)
            return None

    def get_website_tokens(self, website_id: int) -> List[ApiToken]:
        """
        Get all API tokens for a website.

        Args:
            website_id: Website ID

        Returns:
            List of ApiToken objects
        """
        try:
            return self.db.query(ApiToken).filter(
                ApiToken.website_id == website_id
            ).order_by(ApiToken.created_at.desc()).all()

        except Exception as e:
            logger.error(f"Error getting website tokens: {e}", exc_info=True)
            return []

    def delete_token(self, token_id: int, website_id: int) -> bool:
        """
        Delete an API token.

        Args:
            token_id: Token ID
            website_id: Website ID (for authorization)

        Returns:
            True if deleted successfully
        """
        try:
            token = self.db.query(ApiToken).filter(
                ApiToken.id == token_id,
                ApiToken.website_id == website_id
            ).first()

            if not token:
                return False

            self.db.delete(token)
            self.db.commit()
            logger.info(f"API token deleted: id={token_id}")
            return True

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error deleting token: {e}", exc_info=True)
            return False
