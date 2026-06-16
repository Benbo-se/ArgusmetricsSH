"""
Stripe integration router for subscription management.

Handles:
- POST /create-checkout-session - Create Stripe checkout for upgrades
- POST /webhook - Handle Stripe webhook events
- POST /create-billing-portal-session - Customer portal for managing subscription
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
import stripe

from app.database import get_db
from app.config import settings
from app.models.user import User
from app.models.processed_stripe_event import ProcessedStripeEvent
from app.routers.auth import get_current_user
from app.services.ai_quota_service import update_user_ai_quota

logger = logging.getLogger(__name__)

# Initialize Stripe
if settings.STRIPE_SECRET_KEY:
    stripe.api_key = settings.STRIPE_SECRET_KEY
    logger.info("Stripe initialized successfully")
else:
    logger.warning("Stripe not configured - STRIPE_SECRET_KEY missing")

router = APIRouter(prefix="/stripe", tags=["stripe"])


def _plan_from_price_id(price_id: Optional[str]) -> Optional[str]:
    """
    Map a Stripe price ID back to a plan name using configured price IDs.

    Args:
        price_id: Stripe price ID from a subscription line item

    Returns:
        Plan name ('starter', 'pro', 'business') or None if unknown
    """
    if not price_id:
        return None

    price_to_plan = {
        settings.STRIPE_PRICE_ID_STARTER: 'starter',
        settings.STRIPE_PRICE_ID_PRO: 'pro',
        settings.STRIPE_PRICE_ID_BUSINESS: 'business',
    }
    return price_to_plan.get(price_id)


def _subscription_price_id(subscription: dict) -> Optional[str]:
    """
    Extract the price ID from a Stripe subscription object.

    Args:
        subscription: Stripe subscription object (dict-like)

    Returns:
        The first line item's price ID, or None if unavailable
    """
    try:
        items = subscription.get('items', {}).get('data', [])
        if items:
            return items[0].get('price', {}).get('id')
    except (AttributeError, KeyError, TypeError):
        pass
    return None


@router.post("/create-checkout-session")
async def create_checkout_session(
    plan: str,  # 'starter', 'pro', or 'business'
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create Stripe Checkout Session for user to upgrade plan.

    Args:
        plan: Plan to upgrade to ('starter', 'pro', or 'business')
        current_user: Authenticated user
        db: Database session

    Returns:
        RedirectResponse: Redirects directly to Stripe checkout

    Raises:
        HTTPException 400: If Stripe not configured or invalid plan
        HTTPException 500: If Stripe error occurs

    Example:
        POST /api/v1/stripe/create-checkout-session?plan=starter

        Redirects to: https://checkout.stripe.com/...
    """
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe not configured. Please contact support."
        )

    # Get price ID based on plan
    if plan == 'starter':
        price_id = settings.STRIPE_PRICE_ID_STARTER
    elif plan == 'pro':
        price_id = settings.STRIPE_PRICE_ID_PRO
    elif plan == 'business':
        price_id = settings.STRIPE_PRICE_ID_BUSINESS
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid plan: {plan}. Must be 'starter', 'pro', or 'business'."
        )

    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Price ID for {plan} plan not configured."
        )

    logger.info(f"Creating checkout session for user {current_user.email}, plan: {plan}")

    try:
        # Create Stripe Checkout Session
        checkout_session = stripe.checkout.Session.create(
            customer_email=current_user.email,
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f'{settings.BASE_URL}/dashboard?upgrade=success&session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{settings.BASE_URL}/dashboard?upgrade=cancelled',
            metadata={
                'user_id': str(current_user.id),
                'user_email': current_user.email,
                'plan': plan
            },
            # Allow promotional codes
            allow_promotion_codes=True,
            # Billing address collection
            billing_address_collection='required',
        )

        logger.info(f"Checkout session created: {checkout_session.id} for {current_user.email}")

        # Redirect directly to Stripe Checkout
        return RedirectResponse(url=checkout_session.url, status_code=303)

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating checkout session: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to create checkout session. Please try again or contact support."
        )
    except Exception as e:
        logger.error(f"Unexpected error creating checkout session: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create checkout session"
        )


@router.post("/create-billing-portal-session")
async def create_billing_portal_session(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Create Stripe Customer Portal session for managing subscription.

    Allows customers to:
    - Update payment method
    - View invoices
    - Cancel subscription
    - Update billing information

    Args:
        current_user: Authenticated user
        db: Database session

    Returns:
        dict: Contains portal_url for redirect

    Raises:
        HTTPException 400: If no active subscription
        HTTPException 500: If Stripe error occurs
    """
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe not configured. Please contact support."
        )

    if not current_user.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Stripe customer found. Please upgrade first."
        )

    logger.info(f"Creating billing portal session for {current_user.email}")

    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=current_user.stripe_customer_id,
            return_url=f'{settings.BASE_URL}/dashboard',
        )

        logger.info(f"Billing portal session created for {current_user.email}")

        return {
            "portal_url": portal_session.url
        }

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error creating portal session: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to open billing portal. Please try again or contact support."
        )
    except Exception as e:
        logger.error(f"Unexpected error creating portal session: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create billing portal session"
        )


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Handle Stripe webhook events.

    Processes:
    - customer.subscription.created
    - customer.subscription.updated
    - customer.subscription.deleted
    - invoice.payment_succeeded
    - invoice.payment_failed
    - checkout.session.completed

    Args:
        request: FastAPI request object
        db: Database session

    Returns:
        dict: Success status

    Raises:
        HTTPException 400: If invalid payload or signature
    """
    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error("Webhook called but STRIPE_WEBHOOK_SECRET not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook secret not configured"
        )

    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')

    if not sig_header:
        logger.warning("Webhook called without stripe-signature header")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing stripe-signature header"
        )

    try:
        # Verify webhook signature
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
        logger.info(f"Webhook received: {event['type']}, ID: {event['id']}")

    except ValueError as e:
        logger.error(f"Invalid webhook payload: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payload"
        )
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid webhook signature: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature"
        )

    # Handle different event types
    event_type = event['type']
    event_id = event['id']
    data = event['data']['object']

    # Idempotency: skip events we've already processed (Stripe may redeliver)
    already_processed = db.query(ProcessedStripeEvent).filter(
        ProcessedStripeEvent.event_id == event_id
    ).first()
    if already_processed:
        logger.info(f"Webhook event {event_id} ({event_type}) already processed, skipping")
        return {"status": "already_processed"}

    try:
        if event_type == 'checkout.session.completed':
            # Payment successful, subscription created.
            # This is the authoritative place where the plan is set.
            session = data
            user_email = session.get('customer_email') or session['metadata'].get('user_email')
            plan = session['metadata'].get('plan', 'starter')

            user = db.query(User).filter(User.email == user_email).first()
            if user:
                user.stripe_customer_id = session['customer']
                user.subscription_status = 'active'
                user.plan = plan
                # Update AI quota based on new plan
                update_user_ai_quota(user)
                db.commit()
                logger.info(f"✅ Checkout completed for {user_email}, upgraded to {plan} (AI quota: {user.ai_chatbot_quota})")
            else:
                logger.warning(f"Checkout completed but user not found: {user_email}")

        elif event_type == 'customer.subscription.created':
            subscription = data
            customer_id = subscription['customer']

            # Find user by stripe_customer_id
            user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
            if user:
                user.subscription_status = 'active'
                user.stripe_subscription_id = subscription['id']
                # Derive plan from the subscription's price ID. Subscriptions
                # don't carry our 'plan' metadata, so matching against the
                # configured STRIPE_PRICE_ID_* settings is authoritative here.
                # checkout.session.completed remains the canonical place the
                # plan is set, so only overwrite when we can resolve a plan.
                derived_plan = _plan_from_price_id(_subscription_price_id(subscription))
                if derived_plan:
                    user.plan = derived_plan
                else:
                    logger.warning(
                        f"Could not derive plan from subscription {subscription['id']} "
                        f"price ID for {user.email}; leaving plan as '{user.plan}'"
                    )
                # Update AI quota based on new plan
                update_user_ai_quota(user)
                db.commit()
                logger.info(f"✅ Subscription created for {user.email}, plan: {user.plan} (AI quota: {user.ai_chatbot_quota})")

        elif event_type == 'customer.subscription.updated':
            subscription = data
            subscription_id = subscription['id']

            user = db.query(User).filter(User.stripe_subscription_id == subscription_id).first()
            if user:
                # Update subscription status
                sub_status = subscription['status']
                if sub_status == 'active':
                    user.subscription_status = 'active'
                elif sub_status in ['canceled', 'incomplete_expired']:
                    user.subscription_status = 'cancelled'
                elif sub_status == 'past_due':
                    user.subscription_status = 'past_due'

                db.commit()
                logger.info(f"✅ Subscription updated for {user.email}: {sub_status}")

        elif event_type == 'customer.subscription.deleted':
            subscription = data
            subscription_id = subscription['id']

            user = db.query(User).filter(User.stripe_subscription_id == subscription_id).first()
            if user:
                user.subscription_status = 'cancelled'
                user.plan = 'free'
                user.stripe_subscription_id = None
                # Update AI quota - FREE = NO AI
                update_user_ai_quota(user)
                db.commit()
                logger.info(f"✅ Subscription cancelled for {user.email}, reverted to free plan (AI quota: {user.ai_chatbot_quota})")

        elif event_type == 'invoice.payment_succeeded':
            invoice = data
            customer_id = invoice['customer']

            user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
            if user:
                user.subscription_status = 'active'
                db.commit()
                logger.info(f"✅ Payment succeeded for {user.email}")

        elif event_type == 'invoice.payment_failed':
            invoice = data
            customer_id = invoice['customer']

            user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
            if user:
                user.subscription_status = 'past_due'
                db.commit()
                logger.warning(f"⚠️ Payment failed for {user.email}")

        else:
            # Intentionally ignored event type - return 200 so Stripe does not retry.
            logger.info(f"Unhandled webhook event type: {event_type}")

    except Exception as e:
        # Genuine processing failure - roll back and return 500 so Stripe retries.
        db.rollback()
        logger.error(f"Error processing webhook {event_type} ({event_id}): {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing webhook event"
        )

    # Mark this event as processed for idempotency (only after successful handling).
    try:
        db.add(ProcessedStripeEvent(event_id=event_id))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to record processed event {event_id}: {e}", exc_info=True)
        # Don't fail the request - the business logic already succeeded.

    return {"status": "success"}


@router.get("/config")
async def get_stripe_config():
    """
    Get Stripe publishable key for frontend.

    Returns public configuration that frontend needs to initialize Stripe.js.

    Returns:
        dict: Contains publishable_key

    Example:
        GET /api/v1/stripe/config

        Response:
        {
            "publishable_key": "pk_test_...",
            "configured": true
        }
    """
    return {
        "publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
        "configured": bool(settings.STRIPE_SECRET_KEY and settings.STRIPE_PUBLISHABLE_KEY)
    }
