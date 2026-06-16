"""
Password protection service for public dashboards.

Handles hashing and verification of passwords for password-protected
public analytics dashboards.
"""
import bcrypt
import logging

logger = logging.getLogger(__name__)


class PasswordService:
    """
    Service for handling password hashing and verification for public dashboards.

    Uses bcrypt for secure password hashing.
    """

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a password using bcrypt.

        Args:
            password: Plain text password to hash

        Returns:
            str: Hashed password suitable for storage

        Example:
            hashed = PasswordService.hash_password("my_secret_123")
        """
        if not password:
            raise ValueError("Password cannot be empty")

        # Generate salt and hash password
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)

        return hashed.decode('utf-8')

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """
        Verify a password against its hash.

        Args:
            plain_password: Plain text password to verify
            hashed_password: Hashed password from database

        Returns:
            bool: True if password matches, False otherwise

        Example:
            is_valid = PasswordService.verify_password("my_secret_123", hashed)
        """
        if not plain_password or not hashed_password:
            return False

        try:
            return bcrypt.checkpw(
                plain_password.encode('utf-8'),
                hashed_password.encode('utf-8')
            )
        except Exception as e:
            logger.error(f"Error verifying password: {e}")
            return False

    @staticmethod
    def is_strong_password(password: str) -> tuple[bool, str]:
        """
        Check if a password meets minimum strength requirements.

        Requirements:
        - At least 10 characters long
        - Contains at least one letter AND one digit

        Args:
            password: Password to validate

        Returns:
            tuple: (is_valid, error_message)
                - is_valid: True if password is strong enough
                - error_message: Empty string if valid, error description if not

        Example:
            is_valid, error = PasswordService.is_strong_password("abc123")
            if not is_valid:
                print(f"Weak password: {error}")
        """
        if not password:
            return False, "Password cannot be empty"

        if len(password) < 10:
            return False, "Password must be at least 10 characters long"

        if not any(c.isalpha() for c in password):
            return False, "Password must contain at least one letter"

        if not any(c.isdigit() for c in password):
            return False, "Password must contain at least one digit"

        return True, ""
