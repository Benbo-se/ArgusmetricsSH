"""
Pydantic schemas for website management endpoints.

Defines request and response models for:
- Website creation and management
- Website listing and retrieval
- Website updates
"""
from pydantic import BaseModel, Field, HttpUrl, field_validator, EmailStr, model_validator
from typing import Optional, List, Literal
from datetime import datetime


class WebsiteCreate(BaseModel):
    """
    Request schema for creating a new website.

    Attributes:
        name: Website name/label for identification
        domain: Website domain (validated as URL)

    Example:
        {
            "name": "My Blog",
            "domain": "https://myblog.com"
        }
    """
    name: str = Field(
        ...,
        description="Website name/label for identification",
        min_length=1,
        max_length=255,
        example="My Blog"
    )
    domain: str = Field(
        ...,
        description="Website domain URL (must be valid URL format)",
        min_length=1,
        max_length=255,
        example="https://myblog.com"
    )

    @field_validator('domain')
    @classmethod
    def validate_domain_url(cls, v: str) -> str:
        """
        Validate that domain is a valid URL format.

        Args:
            v: Domain value to validate

        Returns:
            str: Validated domain

        Raises:
            ValueError: If domain is not a valid URL
        """
        # Remove trailing slashes for consistency
        v = v.rstrip('/')

        # Ensure it has a protocol
        if not v.startswith(('http://', 'https://')):
            raise ValueError('Domain must include protocol (http:// or https://)')

        # Basic URL validation
        if '.' not in v.split('://', 1)[1]:
            raise ValueError('Domain must be a valid URL')

        return v

    class Config:
        json_schema_extra = {
            "example": {
                "name": "My Blog",
                "domain": "https://myblog.com"
            }
        }


class WebsiteResponse(BaseModel):
    """
    Response schema for website information.

    Attributes:
        id: Website ID (primary key)
        name: Website name/label
        domain: Website domain URL
        tracking_code: Unique tracking code for analytics
        is_active: Whether tracking is active for this website
        is_verified: Whether domain ownership has been verified via DNS
        verification_token: DNS verification token (shown until verified)
        verified_at: Timestamp when domain was verified
        created_at: Timestamp when website was created
        updated_at: Timestamp when website was last updated

    Example:
        {
            "id": 1,
            "name": "My Blog",
            "domain": "https://myblog.com",
            "tracking_code": "abc12345",
            "is_active": true,
            "is_verified": false,
            "verification_token": "abc123xyz456...",
            "verified_at": null,
            "created_at": "2024-01-01T12:00:00Z",
            "updated_at": "2024-01-01T12:00:00Z"
        }
    """
    id: int = Field(
        ...,
        description="Website ID (primary key)",
        example=1
    )
    name: str = Field(
        ...,
        description="Website name/label",
        example="My Blog"
    )
    domain: str = Field(
        ...,
        description="Website domain URL",
        example="https://myblog.com"
    )
    tracking_code: str = Field(
        ...,
        description="Unique tracking code for analytics",
        example="abc12345"
    )
    is_active: bool = Field(
        ...,
        description="Whether tracking is active for this website",
        example=True
    )
    is_verified: bool = Field(
        ...,
        description="Whether domain ownership has been verified via DNS",
        example=False
    )
    verification_token: Optional[str] = Field(
        None,
        description="DNS verification token (shown until verified)",
        example="abc123xyz456def789ghi012jkl345mno678pqr901"
    )
    verified_at: Optional[datetime] = Field(
        None,
        description="Timestamp when domain was verified",
        example=None
    )
    created_at: Optional[datetime] = Field(
        None,
        description="Timestamp when website was created",
        example="2024-01-01T12:00:00Z"
    )
    updated_at: Optional[datetime] = Field(
        None,
        description="Timestamp when website was last updated",
        example="2024-01-01T12:00:00Z"
    )
    email_reports_enabled: bool = Field(
        False,
        description="Whether email reports are enabled",
        example=False
    )
    email_reports_frequency: Optional[str] = Field(
        None,
        description="Report frequency (weekly or monthly)",
        example="weekly"
    )
    email_reports_recipient: Optional[str] = Field(
        None,
        description="Email address to send reports to",
        example="user@example.com"
    )
    email_reports_day: Optional[int] = Field(
        None,
        description="Day for sending reports",
        example=1
    )
    is_public: bool = Field(
        False,
        description="Whether public dashboard is enabled",
        example=False
    )
    public_url: Optional[str] = Field(
        None,
        description="Public dashboard URL (only if is_public=True)",
        example="https://analytics.example.com/public/abc123xyz456"
    )
    public_share_token: Optional[str] = Field(
        None,
        description="Public share token for generating public dashboard URL"
    )

    @model_validator(mode='after')
    def compute_public_url(self):
        """Compute public_url from is_public and public_share_token."""
        if self.is_public and self.public_share_token:
            from app.config import settings
            self.public_url = f"{settings.BASE_URL.rstrip('/')}/public/{self.public_share_token}"
        else:
            self.public_url = None
        return self

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": 1,
                "name": "My Blog",
                "domain": "https://myblog.com",
                "tracking_code": "abc12345",
                "is_active": True,
                "is_verified": False,
                "verification_token": "abc123xyz456def789ghi012jkl345mno678pqr901",
                "verified_at": None,
                "created_at": "2024-01-01T12:00:00Z",
                "updated_at": "2024-01-01T12:00:00Z",
                "email_reports_enabled": False,
                "email_reports_frequency": None,
                "email_reports_recipient": None,
                "email_reports_day": None,
                "is_public": False,
                "public_url": None
            }
        }


class WebsiteUpdate(BaseModel):
    """
    Request schema for updating a website.

    Attributes:
        name: Website name/label (optional)
        is_active: Whether tracking is active (optional)

    Note: At least one field must be provided for update.

    Example:
        {
            "name": "My Updated Blog",
            "is_active": false
        }
    """
    name: Optional[str] = Field(
        None,
        description="Website name/label",
        min_length=1,
        max_length=255,
        example="My Updated Blog"
    )
    is_active: Optional[bool] = Field(
        None,
        description="Whether tracking is active for this website",
        example=False
    )

    @field_validator('name', 'is_active')
    @classmethod
    def at_least_one_field(cls, v, info):
        """Ensure at least one field is provided for update."""
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "name": "My Updated Blog",
                "is_active": False
            }
        }


class WebsiteListResponse(BaseModel):
    """
    Response schema for listing websites.

    Attributes:
        websites: List of websites
        total: Total number of websites

    Example:
        {
            "websites": [
                {
                    "id": 1,
                    "name": "My Blog",
                    "domain": "https://myblog.com",
                    "tracking_code": "abc12345",
                    "is_active": true,
                    "created_at": "2024-01-01T12:00:00Z",
                    "updated_at": "2024-01-01T12:00:00Z"
                }
            ],
            "total": 1
        }
    """
    websites: List[WebsiteResponse] = Field(
        ...,
        description="List of websites"
    )
    total: int = Field(
        ...,
        description="Total number of websites",
        example=1
    )

    class Config:
        json_schema_extra = {
            "example": {
                "websites": [
                    {
                        "id": 1,
                        "name": "My Blog",
                        "domain": "https://myblog.com",
                        "tracking_code": "abc12345",
                        "is_active": True,
                        "created_at": "2024-01-01T12:00:00Z",
                        "updated_at": "2024-01-01T12:00:00Z"
                    }
                ],
                "total": 1
            }
        }


class DomainVerificationInstructions(BaseModel):
    """
    Response schema for domain verification instructions.

    Attributes:
        dns_record: Full DNS record name (_argusmetrics.domain.com)
        record_type: DNS record type (TXT)
        record_value: The verification token value
        instructions: Step-by-step instructions for user

    Example:
        {
            "dns_record": "_argusmetrics.REDACTED.se",
            "record_type": "TXT",
            "record_value": "abc123xyz456...",
            "instructions": "To verify ownership..."
        }
    """
    dns_record: str = Field(
        ...,
        description="Full DNS record name",
        example="_argusmetrics.REDACTED.se"
    )
    record_type: str = Field(
        ...,
        description="DNS record type",
        example="TXT"
    )
    record_value: str = Field(
        ...,
        description="The verification token value",
        example="abc123xyz456def789ghi012jkl345mno678pqr901"
    )
    instructions: str = Field(
        ...,
        description="Step-by-step instructions"
    )


class DomainVerificationResult(BaseModel):
    """
    Response schema for domain verification attempt.

    Attributes:
        verified: Whether verification was successful
        message: Human-readable result message
        verified_at: Timestamp when verified (if successful)

    Example:
        {
            "verified": true,
            "message": "Domain verified successfully!",
            "verified_at": "2024-01-01T12:30:00Z"
        }
    """
    verified: bool = Field(
        ...,
        description="Whether verification was successful",
        example=True
    )
    message: str = Field(
        ...,
        description="Human-readable result message",
        example="Domain verified successfully! TXT record found at _argusmetrics.REDACTED.se"
    )
    verified_at: Optional[datetime] = Field(
        None,
        description="Timestamp when verified (if successful)",
        example="2024-01-01T12:30:00Z"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "verified": True,
                "message": "Domain verified successfully!",
                "verified_at": "2024-01-01T12:30:00Z"
            }
        }


class EmailReportsConfig(BaseModel):
    """
    Request schema for configuring email reports.

    Attributes:
        enabled: Whether email reports are enabled
        frequency: Report frequency ('weekly' or 'monthly')
        recipient: Email address to send reports to
        day: Day for sending (1-7 for weekly, 1-31 for monthly)

    Example:
        {
            "enabled": true,
            "frequency": "weekly",
            "recipient": "user@example.com",
            "day": 1
        }
    """
    enabled: bool = Field(
        ...,
        description="Whether email reports are enabled",
        example=True
    )
    frequency: Literal['weekly', 'monthly'] = Field(
        ...,
        description="Report frequency (weekly or monthly)",
        example="weekly"
    )
    recipient: EmailStr = Field(
        ...,
        description="Email address to send reports to",
        example="user@example.com"
    )
    day: int = Field(
        ...,
        description="Day for sending reports (1-7 for weekly Mon-Sun, 1-31 for monthly)",
        ge=1,
        le=31,
        example=1
    )

    @field_validator('day')
    @classmethod
    def validate_day_for_frequency(cls, v: int, info) -> int:
        """
        Validate that day is appropriate for frequency.

        For weekly: 1-7 (Monday-Sunday)
        For monthly: 1-31 (day of month)
        """
        # Get frequency from the validation context
        frequency = info.data.get('frequency')

        if frequency == 'weekly' and not (1 <= v <= 7):
            raise ValueError('Day must be between 1-7 for weekly reports (1=Monday, 7=Sunday)')
        elif frequency == 'monthly' and not (1 <= v <= 31):
            raise ValueError('Day must be between 1-31 for monthly reports')

        return v

    class Config:
        json_schema_extra = {
            "example": {
                "enabled": True,
                "frequency": "weekly",
                "recipient": "user@example.com",
                "day": 1
            }
        }


class PublicAccessConfig(BaseModel):
    """
    Request schema for toggling public dashboard access.

    Attributes:
        is_public: Whether to enable or disable public access

    Example:
        {
            "is_public": true
        }
    """
    is_public: bool = Field(
        ...,
        description="Whether to enable public dashboard access",
        example=True
    )

    class Config:
        json_schema_extra = {
            "example": {
                "is_public": True
            }
        }


# Team Management Schemas


class TeamMember(BaseModel):
    """
    Response schema for team member information.

    Attributes:
        id: Member ID
        user_email: Email of team member
        role: Member role (owner, admin, viewer)
        status: Member status (pending, active, revoked)
        invited_by: Email of user who invited this member
        invited_at: Timestamp when invitation was sent
        accepted_at: Timestamp when invitation was accepted

    Example:
        {
            "id": 1,
            "user_email": "team@example.com",
            "role": "admin",
            "status": "active",
            "invited_by": "owner@example.com",
            "invited_at": "2024-01-01T12:00:00Z",
            "accepted_at": "2024-01-01T12:30:00Z"
        }
    """
    id: int = Field(..., description="Member ID", example=1)
    user_email: EmailStr = Field(..., description="Email of team member", example="team@example.com")
    role: str = Field(..., description="Member role", example="admin")
    status: str = Field(..., description="Member status", example="active")
    invited_by: EmailStr = Field(..., description="Email of user who invited", example="owner@example.com")
    invited_at: datetime = Field(..., description="When invitation was sent", example="2024-01-01T12:00:00Z")
    accepted_at: Optional[datetime] = Field(None, description="When invitation was accepted", example="2024-01-01T12:30:00Z")

    @field_validator('role', mode='before')
    @classmethod
    def coerce_role(cls, v):
        return v.value if hasattr(v, 'value') else v

    @field_validator('status', mode='before')
    @classmethod
    def coerce_status(cls, v):
        return v.value if hasattr(v, 'value') else v

    class Config:
        from_attributes = True


class TeamMembersList(BaseModel):
    """
    Response schema for listing team members.

    Attributes:
        members: List of team members
        total: Total number of members

    Example:
        {
            "members": [...],
            "total": 3
        }
    """
    members: List[TeamMember] = Field(..., description="List of team members")
    total: int = Field(..., description="Total number of members", example=3)


class InviteMemberRequest(BaseModel):
    """
    Request schema for inviting a new team member.

    Attributes:
        email: Email address of person to invite
        role: Role to assign (admin or viewer, cannot invite as owner)

    Example:
        {
            "email": "newmember@example.com",
            "role": "admin"
        }
    """
    email: EmailStr = Field(..., description="Email address to invite", example="newmember@example.com")
    role: Literal['admin', 'viewer'] = Field(..., description="Role to assign", example="admin")

    class Config:
        json_schema_extra = {
            "example": {
                "email": "newmember@example.com",
                "role": "admin"
            }
        }


class InviteResponse(BaseModel):
    """
    Response schema for team invitation.

    Attributes:
        message: Success message
        member: Created team member (with pending status)
        invite_url: Magic link for accepting invitation (DEV mode only)

    Example:
        {
            "message": "Invitation sent to newmember@example.com",
            "member": {...}
        }
    """
    message: str = Field(..., description="Success message", example="Invitation sent successfully")
    member: TeamMember = Field(..., description="Created team member")
    invite_url: Optional[str] = Field(None, description="Invite URL (shown if email failed or in DEV mode)")
    email_sent: bool = Field(False, description="Whether the invitation email was sent successfully")


class ChangeRoleRequest(BaseModel):
    """
    Request schema for changing a member's role.

    Attributes:
        role: New role to assign

    Example:
        {
            "role": "viewer"
        }
    """
    role: Literal['admin', 'viewer'] = Field(..., description="New role", example="viewer")

    class Config:
        json_schema_extra = {
            "example": {
                "role": "viewer"
            }
        }


class InviteDetails(BaseModel):
    """
    Response schema for invite details (for accepting invitation).

    Attributes:
        website_name: Name of website being invited to
        website_domain: Domain of website
        role: Role being offered
        invited_by: Email of person who invited

    Example:
        {
            "website_name": "My Blog",
            "website_domain": "https://myblog.com",
            "role": "admin",
            "invited_by": "owner@example.com"
        }
    """
    website_name: str = Field(..., description="Website name", example="My Blog")
    website_domain: str = Field(..., description="Website domain", example="https://myblog.com")
    role: str = Field(..., description="Role offered", example="admin")
    invited_by: str = Field(..., description="Who sent invite", example="owner@example.com")


class AcceptInviteResponse(BaseModel):
    """
    Response schema for accepting invitation.

    Attributes:
        message: Success message
        website_id: ID of website joined
        role: Role assigned

    Example:
        {
            "message": "Invitation accepted successfully",
            "website_id": 1,
            "role": "admin"
        }
    """
    message: str = Field(..., description="Success message", example="Invitation accepted")
    website_id: int = Field(..., description="Website ID", example=1)
    role: str = Field(..., description="Role assigned", example="admin")
