"""
Pydantic schemas for authentication endpoints.

Defines request and response models for:
- User signup/registration
- Email verification
- Session management
"""
from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional


class SignupRequest(BaseModel):
    """
    Request schema for user signup/registration.

    Attributes:
        email: User's email address (validated as proper email format)

    Example:
        {
            "email": "user@example.com"
        }
    """
    email: EmailStr = Field(
        ...,
        description="User's email address for registration",
        example="user@example.com"
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Password (validated against the password rules)"
    )
    # Anti-bot fields (filled by the signup template, never by humans):
    # `website` is an off-screen honeypot that must stay empty; `form_ts` is
    # the epoch-ms the form rendered — submissions faster than a human can
    # type are rejected.
    website: Optional[str] = Field(default=None, max_length=255)
    form_ts: Optional[float] = Field(default=None)

    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "password": "correct-horse-battery"
            }
        }


class LoginRequest(BaseModel):
    """Password login."""
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=200)


class VerifyCodeRequest(BaseModel):
    """Verify email with the 6-digit code from the verification email."""
    email: EmailStr
    code: str = Field(..., min_length=1, max_length=16)


class ResendVerificationRequest(BaseModel):
    """Re-send the verification email."""
    email: EmailStr


class RequestResetRequest(BaseModel):
    """Request a password-reset link."""
    email: EmailStr


class SetPasswordRequest(BaseModel):
    """Complete a password reset with the emailed token."""
    token: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1, max_length=200)


class SignupResponse(BaseModel):
    """
    Response schema for successful signup.

    Attributes:
        message: Success message
        email: Email address that was registered

    Example:
        {
            "message": "Verification email sent. Please check your inbox.",
            "email": "user@example.com"
        }
    """
    message: str = Field(
        ...,
        description="Success message describing next steps"
    )
    email: str = Field(
        ...,
        description="Email address that was registered"
    )
    verify_url: Optional[str] = Field(
        None,
        description="Verification URL (only provided in dev mode when SMTP not configured)"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "message": "Verification email sent. Please check your inbox.",
                "email": "user@example.com"
            }
        }
    }


class VerifyRequest(BaseModel):
    """
    Request schema for email verification.

    Attributes:
        token: Magic link token from verification email

    Example:
        {
            "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
        }
    """
    token: str = Field(
        ...,
        description="Magic link token from verification email",
        min_length=10
    )

    class Config:
        json_schema_extra = {
            "example": {
                "token": "InVzZXJAZXhhbXBsZS5jb20i.ZkF8Xw.1a2b3c4d5e6f"
            }
        }


class VerifyResponse(BaseModel):
    """
    Response schema for successful email verification.

    Attributes:
        message: Success message
        email: Verified email address
        session_token: Session token for authentication
        expires_at: ISO timestamp when session expires

    Example:
        {
            "message": "Email verified successfully",
            "email": "user@example.com",
            "session_token": "a1b2c3d4e5f6...",
            "expires_at": "2024-01-15T12:00:00Z"
        }
    """
    message: str = Field(
        ...,
        description="Success message"
    )
    email: str = Field(
        ...,
        description="Verified email address"
    )
    session_token: str = Field(
        ...,
        description="Session token for authentication"
    )
    expires_at: str = Field(
        ...,
        description="ISO timestamp when session expires"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Email verified successfully",
                "email": "user@example.com",
                "session_token": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
                "expires_at": "2024-01-15T12:00:00Z"
            }
        }


class LogoutResponse(BaseModel):
    """
    Response schema for logout.

    Attributes:
        message: Success message

    Example:
        {
            "message": "Logged out successfully"
        }
    """
    message: str = Field(
        ...,
        description="Success message"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Logged out successfully"
            }
        }


class ErrorResponse(BaseModel):
    """
    Standard error response schema.

    Attributes:
        error: Always true for error responses
        message: Error message describing what went wrong
        status_code: HTTP status code

    Example:
        {
            "error": true,
            "message": "Invalid token",
            "status_code": 400
        }
    """
    error: bool = Field(
        default=True,
        description="Indicates this is an error response"
    )
    message: str = Field(
        ...,
        description="Error message"
    )
    status_code: int = Field(
        ...,
        description="HTTP status code"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "error": True,
                "message": "Invalid or expired token",
                "status_code": 400
            }
        }
