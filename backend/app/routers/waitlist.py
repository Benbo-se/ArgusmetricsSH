"""Joining the list of people to tell when hosted signup opens.

Public, because the page it serves is public. That makes it the same shape of
endpoint as tracking: anyone can call it, so it can do exactly one thing and
nothing else. The insert runs through a SECURITY DEFINER function; there is no
policy anywhere that would let this caller read the table back.

Two things it deliberately will not tell you. It answers identically whether
the address was new or already on the list, so it cannot be used to check
whether someone signed up. And it accepts a closed-registration address
without comment, because refusing would say the same thing more slowly.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db, set_rls_context
from app.utils.network import get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter()


class WaitlistRequest(BaseModel):
    email: EmailStr
    #: Which page it came from, so a CTA that works can be told from one
    #: nobody clicks. Truncated and never used to identify anyone.
    source: Optional[str] = Field(default=None, max_length=64)
    #: Honeypot. Off-screen in the form, so anything that fills it is not a
    #: person. Named `website` because that is what a bot expects to find.
    website: Optional[str] = Field(default=None, max_length=255)


class WaitlistResponse(BaseModel):
    message: str


@router.post("", response_model=WaitlistResponse, status_code=status.HTTP_200_OK)
@router.post("/", response_model=WaitlistResponse, status_code=status.HTTP_200_OK)
async def join_waitlist(
    body: WaitlistRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Record an address to notify when hosted signup opens."""
    from app.middleware.rate_limit import rate_limiter

    # Silently accepted and silently dropped. A bot that is told it failed
    # tries something else; one that is told it worked goes away.
    if body.website:
        logger.info("Waitlist honeypot triggered")
        return WaitlistResponse(message="Thanks. We will let you know.")

    ip = get_client_ip(request)
    email = body.email.strip().lower()
    if (
        # Twenty per address per hour rather than a handful: an office behind
        # one NAT is one IP, and locking out the fifth colleague to join is a
        # worse outcome than the flood this is guarding against, which needs
        # many addresses to be worth anything anyway.
        rate_limiter.is_rate_limited(f"waitlist:ip:{ip}", limit=20, window_seconds=3600)
        or rate_limiter.is_rate_limited(
            f"waitlist:email:{email}", limit=3, window_seconds=3600
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Try again later.",
        )

    try:
        # The job context, because that is the one the table's write policy
        # names. The function is SECURITY DEFINER so it would work regardless;
        # declaring the context keeps this consistent with every other writer.
        set_rls_context(db, context="job")
        db.execute(
            text("SELECT argus_join_waitlist(:email, :source)"),
            {"email": email, "source": (body.source or "")[:64] or None},
        )
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error(f"Could not record a waitlist address: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not save that right now. Please try again.",
        )

    # The same answer either way: whether the address was already there is not
    # this endpoint's to disclose.
    return WaitlistResponse(message="Thanks. We will let you know.")
