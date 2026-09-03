"""
Website router for managing website tracking configuration.

Provides endpoints for:
- POST / - Create new website
- GET / - List user's websites
- GET /{website_id} - Get single website
- PUT /{website_id} - Update website
- DELETE /{website_id} - Delete website
"""
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.website_service import WebsiteService
from app.services.domain_verification_service import domain_verification_service
from app.services.team_service import TeamService
from app.schemas.website import (
    WebsiteCreate,
    WebsiteResponse,
    WebsiteUpdate,
    WebsiteListResponse,
    DomainVerificationInstructions,
    DomainVerificationResult,
    EmailReportsConfig,
    PublicAccessConfig,
    TeamMembersList,
    InviteMemberRequest,
    InviteResponse,
    ChangeRoleRequest,
    TeamMember,
    InviteDetails,
    AcceptInviteResponse,
)
from app.schemas.auth import ErrorResponse
from app.models.user import User
from app.routers.auth import get_current_user

logger = logging.getLogger(__name__)

# Create router
router = APIRouter()


def get_website_service(db: Session = Depends(get_db)) -> WebsiteService:
    """
    Dependency to get WebsiteService instance.

    Args:
        db: Database session from FastAPI dependency

    Returns:
        WebsiteService: Initialized website service
    """
    return WebsiteService(db)


@router.post(
    "/",
    response_model=WebsiteResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {
            "description": "Website created successfully",
            "model": WebsiteResponse
        },
        400: {
            "description": "Invalid input or domain already exists",
            "model": ErrorResponse
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse
        }
    }
)
async def create_website(
    request: WebsiteCreate,
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service)
) -> WebsiteResponse:
    """
    Create a new website for tracking.

    Creates a new website record with a unique tracking code. The domain
    must be unique across all users. Requires authentication.

    Args:
        request: Website creation request with name and domain
        current_user: Current authenticated user (from dependency)
        website_service: Website service instance

    Returns:
        WebsiteResponse: Created website with tracking code

    Raises:
        HTTPException: 400 if domain already exists or invalid input
        HTTPException: 401 if not authenticated
        HTTPException: 500 if server error occurs

    Example:
        POST /websites
        Authorization: Bearer <token>
        {
            "name": "My Blog",
            "domain": "https://myblog.com"
        }

        Response:
        {
            "id": 1,
            "name": "My Blog",
            "domain": "https://myblog.com",
            "tracking_code": "a1b2c3d4",
            "is_active": true,
            "created_at": "2024-01-01T12:00:00Z",
            "updated_at": null
        }
    """
    logger.info(f"Website creation request from user: {current_user.email}")

    try:
        website = website_service.create_website(
            user_email=current_user.email,
            name=request.name,
            domain=request.domain
        )

        logger.info(f"Website created successfully: {website.id} for user {current_user.email}")

        return WebsiteResponse.model_validate(website)

    except ValueError as e:
        logger.warning(f"Validation error during website creation: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    except Exception as e:
        logger.error(f"Unexpected error during website creation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the website. Please try again."
        )


@router.get(
    "/",
    response_model=WebsiteListResponse,
    responses={
        200: {
            "description": "List of user's websites",
            "model": WebsiteListResponse
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse
        }
    }
)
async def list_websites(
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service)
) -> WebsiteListResponse:
    """
    List all websites for the current user.

    Retrieves all websites owned by the authenticated user, ordered by
    creation date (newest first). Requires authentication.

    Args:
        current_user: Current authenticated user (from dependency)
        website_service: Website service instance

    Returns:
        WebsiteListResponse: List of websites and total count

    Raises:
        HTTPException: 401 if not authenticated
        HTTPException: 500 if server error occurs

    Example:
        GET /websites
        Authorization: Bearer <token>

        Response:
        {
            "websites": [
                {
                    "id": 1,
                    "name": "My Blog",
                    "domain": "https://myblog.com",
                    "tracking_code": "a1b2c3d4",
                    "is_active": true,
                    "created_at": "2024-01-01T12:00:00Z",
                    "updated_at": null
                }
            ],
            "total": 1
        }
    """
    logger.info(f"Website list request from user: {current_user.email}")

    try:
        websites = website_service.get_user_websites(current_user.email)

        logger.debug(f"Returning {len(websites)} websites for user {current_user.email}")

        return WebsiteListResponse(
            websites=[WebsiteResponse.model_validate(w) for w in websites],
            total=len(websites)
        )

    except Exception as e:
        logger.error(f"Unexpected error listing websites: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while retrieving websites. Please try again."
        )


@router.get(
    "/{website_id}",
    response_model=WebsiteResponse,
    responses={
        200: {
            "description": "Website details",
            "model": WebsiteResponse
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        },
        404: {
            "description": "Website not found or access denied",
            "model": ErrorResponse
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse
        }
    }
)
async def get_website(
    website_id: int,
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service)
) -> WebsiteResponse:
    """
    Get a specific website by ID.

    Retrieves website details. Only returns the website if it belongs to
    the authenticated user. Requires authentication.

    Args:
        website_id: ID of the website to retrieve
        current_user: Current authenticated user (from dependency)
        website_service: Website service instance

    Returns:
        WebsiteResponse: Website details

    Raises:
        HTTPException: 401 if not authenticated
        HTTPException: 404 if website not found or access denied
        HTTPException: 500 if server error occurs

    Example:
        GET /websites/1
        Authorization: Bearer <token>

        Response:
        {
            "id": 1,
            "name": "My Blog",
            "domain": "https://myblog.com",
            "tracking_code": "a1b2c3d4",
            "is_active": true,
            "created_at": "2024-01-01T12:00:00Z",
            "updated_at": null
        }
    """
    logger.info(f"Website details request for {website_id} from user: {current_user.email}")

    try:
        website = website_service.get_website_by_id(website_id, current_user.email)

        if not website:
            logger.warning(f"Website {website_id} not found for user {current_user.email}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Website not found or access denied"
            )

        logger.debug(f"Returning website {website_id} for user {current_user.email}")

        return WebsiteResponse.model_validate(website)

    except HTTPException:
        # Re-raise HTTP exceptions
        raise

    except Exception as e:
        logger.error(f"Unexpected error retrieving website {website_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while retrieving the website. Please try again."
        )


@router.put(
    "/{website_id}",
    response_model=WebsiteResponse,
    responses={
        200: {
            "description": "Website updated successfully",
            "model": WebsiteResponse
        },
        400: {
            "description": "Invalid input or no fields to update",
            "model": ErrorResponse
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        },
        404: {
            "description": "Website not found or access denied",
            "model": ErrorResponse
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse
        }
    }
)
async def update_website(
    website_id: int,
    request: WebsiteUpdate,
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service),
    db: Session = Depends(get_db)
) -> WebsiteResponse:
    """
    Update a website's information.

    Updates website name and/or active status. Only the owner can update
    the website. Requires authentication.

    Args:
        website_id: ID of the website to update
        request: Update request with optional name and is_active fields
        current_user: Current authenticated user (from dependency)
        website_service: Website service instance

    Returns:
        WebsiteResponse: Updated website details

    Raises:
        HTTPException: 400 if invalid input or no fields to update
        HTTPException: 401 if not authenticated
        HTTPException: 404 if website not found or access denied
        HTTPException: 500 if server error occurs

    Example:
        PUT /websites/1
        Authorization: Bearer <token>
        {
            "name": "My Updated Blog",
            "is_active": false
        }

        Response:
        {
            "id": 1,
            "name": "My Updated Blog",
            "domain": "https://myblog.com",
            "tracking_code": "a1b2c3d4",
            "is_active": false,
            "created_at": "2024-01-01T12:00:00Z",
            "updated_at": "2024-01-02T10:30:00Z"
        }
    """
    logger.info(f"Website update request for {website_id} from user: {current_user.email}")

    # Renaming/deactivating a site is not for viewers
    from app.services.team_service import require_website_role_or_404
    from app.models.website_member import MemberRole
    require_website_role_or_404(db, current_user.email, website_id, MemberRole.ADMIN)

    # Validate that at least one field is provided
    if request.name is None and request.is_active is None:
        logger.warning("No update fields provided")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one field (name or is_active) must be provided for update"
        )

    try:
        website = website_service.update_website(
            website_id=website_id,
            user_email=current_user.email,
            name=request.name,
            is_active=request.is_active
        )

        logger.info(f"Website {website_id} updated successfully for user {current_user.email}")

        return WebsiteResponse.model_validate(website)

    except ValueError as e:
        error_msg = str(e)
        logger.warning(f"Validation error during website update: {error_msg}")

        # Determine appropriate status code
        if "not found" in error_msg.lower() or "access denied" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )

    except Exception as e:
        logger.error(f"Unexpected error updating website {website_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating the website. Please try again."
        )


@router.delete(
    "/{website_id}",
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "Website deleted successfully"
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        },
        404: {
            "description": "Website not found or access denied",
            "model": ErrorResponse
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse
        }
    }
)
async def delete_website(
    website_id: int,
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service),
    db: Session = Depends(get_db)
) -> dict:
    """
    Delete a website.

    Permanently deletes a website and all associated data. Only the owner
    can delete the website. Requires authentication.

    Args:
        website_id: ID of the website to delete
        current_user: Current authenticated user (from dependency)
        website_service: Website service instance

    Returns:
        dict: Success message

    Raises:
        HTTPException: 401 if not authenticated
        HTTPException: 404 if website not found or access denied
        HTTPException: 500 if server error occurs

    Example:
        DELETE /websites/1
        Authorization: Bearer <token>

        Response:
        {
            "message": "Website deleted successfully"
        }
    """
    logger.info(f"Website deletion request for {website_id} from user: {current_user.email}")

    # Destroying the site and all its data is owner-only
    from app.services.team_service import require_website_role_or_404
    from app.models.website_member import MemberRole
    require_website_role_or_404(db, current_user.email, website_id, MemberRole.OWNER)

    try:
        success = website_service.delete_website(website_id, current_user.email)

        if not success:
            logger.warning(f"Failed to delete website {website_id} for user {current_user.email}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Website not found or access denied"
            )

        logger.info(f"Website {website_id} deleted successfully for user {current_user.email}")

        return {
            "message": "Website deleted successfully"
        }

    except ValueError as e:
        logger.warning(f"Validation error during website deletion: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )

    except HTTPException:
        # Re-raise HTTP exceptions
        raise

    except Exception as e:
        logger.error(f"Unexpected error deleting website {website_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while deleting the website. Please try again."
        )


@router.get(
    "/{website_id}/verification-instructions",
    response_model=DomainVerificationInstructions,
    responses={
        200: {
            "description": "DNS verification instructions",
            "model": DomainVerificationInstructions
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        },
        404: {
            "description": "Website not found or access denied",
            "model": ErrorResponse
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse
        }
    }
)
async def get_verification_instructions(
    website_id: int,
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service)
) -> DomainVerificationInstructions:
    """
    Get DNS verification instructions for a website.

    Returns the DNS TXT record details that the user needs to add to verify
    domain ownership. This endpoint can be called at any time to retrieve
    the verification token and instructions.

    Args:
        website_id: ID of the website
        current_user: Current authenticated user
        website_service: Website service instance

    Returns:
        DomainVerificationInstructions: DNS record details and setup instructions

    Raises:
        HTTPException: 401 if not authenticated
        HTTPException: 404 if website not found or access denied
        HTTPException: 500 if server error occurs

    Example:
        GET /websites/1/verification-instructions
        Authorization: Bearer <token>

        Response:
        {
            "dns_record": "_argusmetrics.REDACTED.se",
            "record_type": "TXT",
            "record_value": "abc123xyz456...",
            "instructions": "To verify ownership of REDACTED.se, add the following DNS record:..."
        }
    """
    logger.info(f"Verification instructions request for website {website_id} from user: {current_user.email}")

    try:
        # Get website
        website = website_service.get_website_by_id(website_id, current_user.email)

        if not website:
            logger.warning(f"Website {website_id} not found for user {current_user.email}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Website not found or access denied"
            )

        # Get instructions from verification service
        instructions = domain_verification_service.get_verification_instructions(
            domain=website.domain,
            verification_token=website.verification_token
        )

        logger.debug(f"Returning verification instructions for website {website_id}")

        return DomainVerificationInstructions(**instructions)

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Unexpected error getting verification instructions for website {website_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while retrieving verification instructions. Please try again."
        )


@router.post(
    "/{website_id}/verify-domain",
    response_model=DomainVerificationResult,
    responses={
        200: {
            "description": "Domain verification result",
            "model": DomainVerificationResult
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        },
        404: {
            "description": "Website not found or access denied",
            "model": ErrorResponse
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse
        }
    }
)
async def verify_domain(
    website_id: int,
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service),
    db: Session = Depends(get_db)
) -> DomainVerificationResult:
    """
    Verify domain ownership via DNS TXT record lookup.

    Performs a DNS lookup to check if the verification token exists as a TXT
    record at _argusmetrics.<domain>. If found and matches, marks the domain
    as verified and allows analytics tracking.

    The verification process:
    1. User adds TXT record: _argusmetrics.domain.com → verification_token
    2. User clicks "Verify Domain"
    3. System performs DNS lookup
    4. If match → domain is verified, tracking enabled
    5. If no match → returns error message with instructions

    Args:
        website_id: ID of the website to verify
        current_user: Current authenticated user
        website_service: Website service instance
        db: Database session

    Returns:
        DomainVerificationResult: Verification result with success status

    Raises:
        HTTPException: 401 if not authenticated
        HTTPException: 404 if website not found or access denied
        HTTPException: 500 if server error occurs

    Example:
        POST /websites/1/verify-domain
        Authorization: Bearer <token>

        Response (Success):
        {
            "verified": true,
            "message": "Domain verified successfully! TXT record found at _argusmetrics.REDACTED.se",
            "verified_at": "2024-01-01T12:30:00Z"
        }

        Response (Failure):
        {
            "verified": false,
            "message": "Verification failed: DNS record _argusmetrics.REDACTED.se not found. Please add the TXT record and try again.",
            "verified_at": null
        }
    """
    logger.info(f"Domain verification request for website {website_id} from user: {current_user.email}")

    try:
        # Get website
        website = website_service.get_website_by_id(website_id, current_user.email)

        if not website:
            logger.warning(f"Website {website_id} not found for user {current_user.email}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Website not found or access denied"
            )

        # Check if already verified
        if website.is_verified:
            logger.info(f"Website {website_id} already verified")
            return DomainVerificationResult(
                verified=True,
                message="Domain is already verified",
                verified_at=website.verified_at
            )

        # Perform DNS verification
        verification_result = domain_verification_service.verify_domain_dns(
            domain=website.domain,
            expected_token=website.verification_token
        )

        logger.info(f"DNS verification result for website {website_id}: {verification_result['verified']}")

        # If verified, update database
        if verification_result["verified"]:
            website = website_service.mark_verified(website_id)

            logger.info(f"Website {website_id} ({website.domain}) verified successfully")

            return DomainVerificationResult(
                verified=True,
                message=verification_result["message"],
                verified_at=website.verified_at
            )
        else:
            # Verification failed - return error message
            logger.warning(f"❌ Domain verification failed for website {website_id}: {verification_result['message']}")

            return DomainVerificationResult(
                verified=False,
                message=verification_result["message"],
                verified_at=None
            )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Unexpected error verifying domain for website {website_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while verifying the domain. Please try again."
        )


@router.put(
    "/{website_id}/email-reports",
    response_model=WebsiteResponse,
    responses={
        200: {
            "description": "Email reports configuration updated successfully",
            "model": WebsiteResponse
        },
        400: {
            "description": "Invalid configuration or validation error",
            "model": ErrorResponse
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        },
        404: {
            "description": "Website not found or access denied",
            "model": ErrorResponse
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse
        }
    }
)
async def update_email_reports(
    website_id: int,
    config: EmailReportsConfig,
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service),
    db: Session = Depends(get_db)
) -> WebsiteResponse:
    """
    Update email reports configuration for a website.

    Configures automated email reports for website analytics. When enabled,
    sends periodic reports (weekly or monthly) to the specified email address.

    Configuration:
    - Frequency: 'weekly' or 'monthly'
    - Day: 1-7 for weekly (1=Monday, 7=Sunday), 1-31 for monthly
    - Recipient: Email address to receive reports

    Args:
        website_id: ID of the website to configure
        config: Email reports configuration
        current_user: Current authenticated user
        website_service: Website service instance

    Returns:
        WebsiteResponse: Updated website with email reports configuration

    Raises:
        HTTPException: 400 if invalid configuration
        HTTPException: 401 if not authenticated
        HTTPException: 404 if website not found or access denied
        HTTPException: 500 if server error occurs

    Example:
        PUT /websites/1/email-reports
        Authorization: Bearer <token>
        {
            "enabled": true,
            "frequency": "weekly",
            "recipient": "user@example.com",
            "day": 1
        }

        Response:
        {
            "id": 1,
            "name": "My Blog",
            "domain": "https://myblog.com",
            "email_reports_enabled": true,
            "email_reports_frequency": "weekly",
            "email_reports_recipient": "user@example.com",
            "email_reports_day": 1,
            ...
        }
    """
    logger.info(f"Email reports update request for website {website_id} from user: {current_user.email}")

    # Reports exfiltrate analytics to an arbitrary address: not for viewers
    from app.services.team_service import require_website_role_or_404
    from app.models.website_member import MemberRole
    require_website_role_or_404(db, current_user.email, website_id, MemberRole.ADMIN)

    try:
        website = website_service.update_email_reports_config(
            website_id=website_id,
            user_email=current_user.email,
            enabled=config.enabled,
            frequency=config.frequency,
            recipient=config.recipient,
            day=config.day
        )

        logger.info(f"Email reports configuration updated for website {website_id}")

        return WebsiteResponse.model_validate(website)

    except ValueError as e:
        error_msg = str(e)
        logger.warning(f"Validation error updating email reports: {error_msg}")

        # Determine appropriate status code
        if "not found" in error_msg.lower() or "access denied" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Unexpected error updating email reports for website {website_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating email reports configuration. Please try again."
        )


@router.put(
    "/{website_id}/public-access",
    response_model=WebsiteResponse,
    responses={
        200: {
            "description": "Public access configuration updated successfully",
            "model": WebsiteResponse
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        },
        404: {
            "description": "Website not found or access denied",
            "model": ErrorResponse
        },
        500: {
            "description": "Internal server error",
            "model": ErrorResponse
        }
    }
)
async def update_public_access(
    website_id: int,
    request: PublicAccessConfig,
    current_user: User = Depends(get_current_user),
    website_service: WebsiteService = Depends(get_website_service),
    db: Session = Depends(get_db)
) -> WebsiteResponse:
    """
    Toggle public dashboard access for a website.

    Enables or disables public dashboard sharing. When enabling for the first time,
    generates a secure random token for the public URL. When disabling, keeps the
    token but sets is_public=False.

    Args:
        website_id: ID of the website
        request: Public access configuration with is_public flag
        current_user: Current authenticated user
        website_service: Website service instance
        db: Database session

    Returns:
        WebsiteResponse: Updated website with public_url if enabled

    Raises:
        HTTPException: 401 if not authenticated
        HTTPException: 404 if website not found or access denied
        HTTPException: 500 if server error occurs

    Example:
        PUT /websites/1/public-access
        Authorization: Bearer <token>
        {
            "is_public": true
        }

        Response:
        {
            "id": 1,
            "name": "My Blog",
            "domain": "https://myblog.com",
            "is_public": true,
            "public_url": "https://analytics.example.com/public/abc123xyz456..."
        }
    """
    logger.info(f"Public access update request for website {website_id} from user: {current_user.email}")

    try:
        from app.models.website_member import MemberRole

        # Publishing a dashboard exposes data publicly: require owner role
        team_service = TeamService(db)
        role = team_service.check_website_access(current_user.email, website_id)
        if not role:
            logger.warning(f"Website {website_id} not found for user {current_user.email}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Website not found or access denied"
            )
        if role != MemberRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You need owner access to change public sharing"
            )

        # Toggle public share via service
        website = website_service.toggle_public_share(website_id, request.is_public)

        logger.info(f"Public access {'enabled' if request.is_public else 'disabled'} for website {website_id}")

        return WebsiteResponse.model_validate(website)

    except HTTPException:
        raise

    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error updating public access for website {website_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while updating public access. Please try again."
        )


def get_team_service(db: Session = Depends(get_db)) -> TeamService:
    """
    Dependency to get TeamService instance.

    Args:
        db: Database session from FastAPI dependency

    Returns:
        TeamService: Initialized team service
    """
    return TeamService(db)


# Team Management Endpoints


@router.get(
    "/{website_id}/members",
    response_model=TeamMembersList,
    responses={
        200: {
            "description": "List of team members",
            "model": TeamMembersList
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        },
        403: {
            "description": "Insufficient permissions",
            "model": ErrorResponse
        },
        404: {
            "description": "Website not found",
            "model": ErrorResponse
        }
    }
)
async def list_team_members(
    website_id: int,
    current_user: User = Depends(get_current_user),
    team_service: TeamService = Depends(get_team_service)
) -> TeamMembersList:
    """
    List all team members for a website.

    Requires authentication and access to the website.

    Args:
        website_id: ID of the website
        current_user: Current authenticated user
        team_service: Team service instance

    Returns:
        TeamMembersList: List of team members

    Raises:
        HTTPException: 401 if not authenticated
        HTTPException: 403 if insufficient permissions
        HTTPException: 404 if website not found
    """
    logger.info(f"Team members list request for website {website_id} from user: {current_user.email}")

    try:
        members = team_service.get_team_members(website_id, current_user.email)

        return TeamMembersList(
            members=[TeamMember.model_validate(m) for m in members],
            total=len(members)
        )

    except ValueError as e:
        logger.warning(f"Access error listing team members: {e}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e)
        )

    except Exception as e:
        logger.error(f"Unexpected error listing team members for website {website_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while retrieving team members. Please try again."
        )


@router.post(
    "/{website_id}/members",
    response_model=InviteResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {
            "description": "Team member invited successfully",
            "model": InviteResponse
        },
        400: {
            "description": "Invalid request or user already invited",
            "model": ErrorResponse
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        },
        403: {
            "description": "Insufficient permissions (must be owner or admin)",
            "model": ErrorResponse
        }
    }
)
async def invite_team_member(
    website_id: int,
    request: InviteMemberRequest,
    current_user: User = Depends(get_current_user),
    team_service: TeamService = Depends(get_team_service)
) -> InviteResponse:
    """
    Invite a new team member to a website.

    Requires owner or admin role. Cannot invite as owner.

    Args:
        website_id: ID of the website
        request: Invitation request with email and role
        current_user: Current authenticated user
        team_service: Team service instance

    Returns:
        InviteResponse: Invitation details and member info

    Raises:
        HTTPException: 400 if invalid request
        HTTPException: 401 if not authenticated
        HTTPException: 403 if insufficient permissions
    """
    logger.info(f"Team invitation request for website {website_id}: inviting {request.email} as {request.role}")

    try:
        from app.models.website_member import MemberRole

        result = team_service.invite_member(
            website_id=website_id,
            inviter_email=current_user.email,
            invitee_email=request.email,
            role=MemberRole(request.role)
        )

        return InviteResponse(
            message=result["message"],
            member=TeamMember.model_validate(result["member"]),
            invite_url=result.get("invite_url"),
            email_sent=result.get("email_sent", False)
        )

    except ValueError as e:
        error_msg = str(e)
        logger.warning(f"Validation error inviting team member: {error_msg}")

        # Determine status code based on error message
        if "don't have access" in error_msg.lower() or "need" in error_msg.lower():
            status_code = status.HTTP_403_FORBIDDEN
        else:
            status_code = status.HTTP_400_BAD_REQUEST

        raise HTTPException(status_code=status_code, detail=error_msg)

    except Exception as e:
        logger.error(f"Unexpected error inviting team member for website {website_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while inviting team member. Please try again."
        )


@router.delete(
    "/{website_id}/members/{member_email}",
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "Team member removed successfully"
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        },
        403: {
            "description": "Insufficient permissions",
            "model": ErrorResponse
        },
        404: {
            "description": "Team member not found",
            "model": ErrorResponse
        }
    }
)
async def remove_team_member(
    website_id: int,
    member_email: str,
    current_user: User = Depends(get_current_user),
    team_service: TeamService = Depends(get_team_service)
) -> dict:
    """
    Remove a team member from a website.

    Requires owner or admin role. Cannot remove owner.

    Args:
        website_id: ID of the website
        member_email: Email of member to remove
        current_user: Current authenticated user
        team_service: Team service instance

    Returns:
        dict: Success message

    Raises:
        HTTPException: 401 if not authenticated
        HTTPException: 403 if insufficient permissions
        HTTPException: 404 if member not found
    """
    logger.info(f"Remove team member request for website {website_id}: removing {member_email}")

    try:
        team_service.remove_member(website_id, current_user.email, member_email)

        return {
            "message": f"Team member {member_email} removed successfully"
        }

    except ValueError as e:
        error_msg = str(e)
        logger.warning(f"Error removing team member: {error_msg}")

        # Determine status code
        if "not found" in error_msg.lower():
            status_code = status.HTTP_404_NOT_FOUND
        elif "don't have access" in error_msg.lower() or "cannot" in error_msg.lower():
            status_code = status.HTTP_403_FORBIDDEN
        else:
            status_code = status.HTTP_400_BAD_REQUEST

        raise HTTPException(status_code=status_code, detail=error_msg)

    except Exception as e:
        logger.error(f"Unexpected error removing team member for website {website_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while removing team member. Please try again."
        )


@router.put(
    "/{website_id}/members/{member_email}/role",
    response_model=TeamMember,
    responses={
        200: {
            "description": "Role changed successfully",
            "model": TeamMember
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        },
        403: {
            "description": "Insufficient permissions (must be owner)",
            "model": ErrorResponse
        },
        404: {
            "description": "Team member not found",
            "model": ErrorResponse
        }
    }
)
async def change_member_role(
    website_id: int,
    member_email: str,
    request: ChangeRoleRequest,
    current_user: User = Depends(get_current_user),
    team_service: TeamService = Depends(get_team_service)
) -> TeamMember:
    """
    Change a team member's role.

    Requires owner role. Cannot change owner's role or assign owner role.

    Args:
        website_id: ID of the website
        member_email: Email of member to update
        request: New role
        current_user: Current authenticated user
        team_service: Team service instance

    Returns:
        TeamMember: Updated team member

    Raises:
        HTTPException: 401 if not authenticated
        HTTPException: 403 if insufficient permissions
        HTTPException: 404 if member not found
    """
    logger.info(f"Change role request for website {website_id}: changing {member_email} to {request.role}")

    try:
        from app.models.website_member import MemberRole

        member = team_service.change_role(
            website_id=website_id,
            changer_email=current_user.email,
            member_email=member_email,
            new_role=MemberRole(request.role)
        )

        return TeamMember.model_validate(member)

    except ValueError as e:
        error_msg = str(e)
        logger.warning(f"Error changing member role: {error_msg}")

        # Determine status code
        if "not found" in error_msg.lower():
            status_code = status.HTTP_404_NOT_FOUND
        elif "don't have access" in error_msg.lower() or "cannot" in error_msg.lower() or "need" in error_msg.lower():
            status_code = status.HTTP_403_FORBIDDEN
        else:
            status_code = status.HTTP_400_BAD_REQUEST

        raise HTTPException(status_code=status_code, detail=error_msg)

    except Exception as e:
        logger.error(f"Unexpected error changing member role for website {website_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while changing member role. Please try again."
        )


# Invitation Acceptance Endpoints (These don't require auth for initial viewing)


@router.get(
    "/invites/{token}",
    response_model=InviteDetails,
    responses={
        200: {
            "description": "Invitation details",
            "model": InviteDetails
        },
        400: {
            "description": "Invalid or expired invitation",
            "model": ErrorResponse
        }
    }
)
async def get_invite_details(
    token: str,
    team_service: TeamService = Depends(get_team_service)
) -> InviteDetails:
    """
    Get details about a pending invitation.

    Does not require authentication. Used to display invitation info before acceptance.

    Args:
        token: Invitation token
        team_service: Team service instance

    Returns:
        InviteDetails: Invitation details

    Raises:
        HTTPException: 400 if invitation invalid or expired
    """
    logger.info(f"Invitation details request for token: {token[:10]}...")

    try:
        details = team_service.get_invite_details(token)

        return InviteDetails(**details)

    except ValueError as e:
        logger.warning(f"Invalid invitation token: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    except Exception as e:
        logger.error(f"Unexpected error getting invitation details: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while retrieving invitation details. Please try again."
        )


@router.post(
    "/invites/{token}/accept",
    response_model=AcceptInviteResponse,
    responses={
        200: {
            "description": "Invitation accepted successfully",
            "model": AcceptInviteResponse
        },
        400: {
            "description": "Invalid, expired, or mismatched invitation",
            "model": ErrorResponse
        },
        401: {
            "description": "Not authenticated",
            "model": ErrorResponse
        }
    }
)
async def accept_invitation(
    token: str,
    current_user: User = Depends(get_current_user),
    team_service: TeamService = Depends(get_team_service)
) -> AcceptInviteResponse:
    """
    Accept a team invitation.

    Requires authentication. User's email must match the invitation.

    Args:
        token: Invitation token
        current_user: Current authenticated user
        team_service: Team service instance

    Returns:
        AcceptInviteResponse: Acceptance confirmation with website_id and role

    Raises:
        HTTPException: 400 if invitation invalid or email mismatch
        HTTPException: 401 if not authenticated
    """
    logger.info(f"Accept invitation request from user: {current_user.email}")

    try:
        result = team_service.accept_invitation(token, current_user.email)

        return AcceptInviteResponse(**result)

    except ValueError as e:
        logger.warning(f"Error accepting invitation: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

    except Exception as e:
        logger.error(f"Unexpected error accepting invitation: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while accepting invitation. Please try again."
        )
