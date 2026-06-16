"""
Chatbot API router for Argusmetrics assistant.
"""
import hashlib
import logging
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.routers.auth import get_current_user
from app.services.ai_quota_service import (
    check_ai_quota,
    increment_ai_usage,
    get_quota_info,
    get_upgrade_message
)
from app.services.conversational_analytics_service import ConversationalAnalyticsService
from app.utils.network import get_client_ip

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chatbot"])

# Demo mode limits
DEMO_QUERY_LIMIT = 3

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    sessionId: str
    context: Optional[dict] = None

class ChatResponse(BaseModel):
    answer: str
    logId: str
    timestamp: str

class FeedbackRequest(BaseModel):
    logId: str
    helpful: bool

# Context about Argusmetrics for AI assistant
ARGUS_CONTEXT = """Du är en hjälpsam AI-assistent för Argusmetrics - en privacy-first webbanalysverktyg.

VIKTIGA FAKTA OM ARGUS METRICS:
- Privacy-first analytics: Ingen cookies, IP-anonymisering, GDPR-compliant
- < 4KB tracking script (mycket liten och snabb)
- Data lagras i Sverige/EU
- Obegränsade websites på alla planer
- Modern stack: FastAPI (Python), PostgreSQL

PRISER (svenska kronor):
- Starter: 79kr/månad - 100,000 pageviews
- Pro: 199kr/månad - 500,000 pageviews
- Business: 499kr/månad - 2,000,000 pageviews

FUNKTIONER:
- Real-time analytics och dashboards
- Pageviews, visitors, bounce rate
- Referrers, countries, devices, browsers
- Top pages, outbound links
- 404 error tracking
- Goals och event tracking
- CSV export
- Team collaboration

SETUP:
1. Registrera konto på argusmetrics.io
2. Lägg till din website
3. Kopiera tracking-koden
4. Klistra in före </head> på din sajt
5. Klart! Tar mindre än 5 minuter.

SUPPORT:
- Email: reda@argusmetrics.io
- Demo: argusmetrics.io/demo (ingen registrering krävs)

Svara kortfattat och hjälpsamt på svenska. Om du inte kan svara exakt, hänvisa till reda@argusmetrics.io."""

async def call_deepseek_api(message: str) -> str:
    """Call DeepSeek API for chatbot responses."""
    if not settings.DEEPSEEK_API_KEY:
        logger.warning("DEEPSEEK_API_KEY not configured, using fallback responses")
        return await fallback_response(message)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

        response = client.chat.completions.create(
            model="deepseek-chat",
            max_tokens=300,
            messages=[
                {"role": "system", "content": ARGUS_CONTEXT},
                {"role": "user", "content": message}
            ],
            temperature=0.7
        )

        return response.choices[0].message.content
    except ImportError:
        logger.error("openai package not installed. Install with: pip install openai")
        return await fallback_response(message)
    except Exception as e:
        logger.error(f"DeepSeek API error: {e}")
        return await fallback_response(message)

async def fallback_response(message: str) -> str:
    """Fallback responses when API is not available."""
    message_lower = message.lower()

    if "spårning" in message_lower or "tracking" in message_lower:
        return "Vi använder en liten JavaScript-fil (< 4KB) som samlar anonym data. Ingen personlig data - vi anonymiserar IP-adresser och använder inga cookies."
    elif "plausible" in message_lower or "skillnad" in message_lower:
        return "Argusmetrics har 98% funktionsparitet med Plausible, men med modern Python stack, JSONB events, 404 tracking, och svensk support. Dessutom billigare!"
    elif "integrit" in message_lower or "privacy" in message_lower:
        return "Vi tar integritet på allvar: ✅ Ingen cookies ✅ IP-anonymisering ✅ Data i Sverige/EU ✅ 100% GDPR-compliant. Du äger din data."
    elif "pris" in message_lower or "kostar" in message_lower:
        return "Starter: 79kr/månad (100k pageviews), Pro: 199kr/månad (500k pageviews), Business: 499kr/månad (2M pageviews). Alla med obegränsade websites!"
    elif "demo" in message_lower or "test" in message_lower:
        return "Testa vår live demo: argusmetrics.io/demo - visar riktig data från vår sajt. Ingen registrering krävs!"
    elif "setup" in message_lower or "installera" in message_lower:
        return "Superenkelt! 1) Registrera konto 2) Lägg till website 3) Kopiera tracking-kod 4) Klistra in före </head> 5) Klart! Tar <5min."
    else:
        return "Tack för din fråga! Jag är Argusmetrics AI-assistent. För snabbare svar: 📧 reda@argusmetrics.io eller 📚 argusmetrics.io/docs"

def _demo_ip_key(client_ip: str) -> str:
    """Stable, non-reversible key derived from the IP (no raw IP stored)."""
    return hashlib.sha256(f"{settings.SECRET_KEY}:{client_ip}".encode()).hexdigest()

def get_demo_query_count(db: Session, ip_key: str) -> int:
    """Count demo queries in the last 24h for this IP key (server-derived)."""
    result = db.execute(text("""
        SELECT COUNT(*)
        FROM demo_chat_sessions
        WHERE client_ip = :ip_key
        AND created_at > NOW() - INTERVAL '24 hours'
    """), {"ip_key": ip_key})
    return result.scalar() or 0

def increment_demo_query(db: Session, session_id: str, ip_key: str):
    """Record a demo query keyed on the hashed IP (client_ip stores the hash)."""
    db.execute(text("""
        INSERT INTO demo_chat_sessions (session_id, client_ip, created_at)
        VALUES (:session_id, :ip_key, NOW())
    """), {"session_id": session_id, "ip_key": ip_key})
    db.commit()

def ensure_demo_table_exists(db: Session):
    """Create demo_chat_sessions table if it doesn't exist."""
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS demo_chat_sessions (
                id SERIAL PRIMARY KEY,
                session_id VARCHAR(255) NOT NULL,
                client_ip VARCHAR(45),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        db.commit()
    except Exception as e:
        logger.error(f"Failed to create demo table: {e}")
        db.rollback()

@router.post("/ask", response_model=ChatResponse)
async def chat_ask(
    request_obj: Request,
    request: ChatRequest,
    db: Session = Depends(get_db)
):
    """
    Chat endpoint with AI-powered responses.
    Uses Anthropic Claude API if configured, falls back to keyword matching.

    Supports demo mode (3 free queries) for anonymous users.
    Authenticated users have quota based on their plan.
    """
    log_id = str(uuid.uuid4())
    current_user = None

    # Try to get authenticated user from header
    auth_header = request_obj.headers.get("authorization")
    if auth_header:
        try:
            # Import inline to avoid circular dependency
            from app.services.auth_service import AuthService
            auth_service = AuthService(db)
            token = auth_header.replace("Bearer ", "")
            current_user = auth_service.validate_session(token)
        except:
            current_user = None

    # Demo mode for anonymous users
    is_demo_mode = (current_user is None)

    if is_demo_mode:
        # Ensure demo table exists
        ensure_demo_table_exists(db)

        # Rate-limit by server-derived IP, not the client-supplied sessionId
        # (a random sessionId per request would otherwise bypass the limit).
        client_ip = get_client_ip(request_obj)
        ip_key = _demo_ip_key(client_ip)

        # Check demo query limit
        demo_count = get_demo_query_count(db, ip_key)

        if demo_count >= DEMO_QUERY_LIMIT:
            logger.info("Demo limit reached")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Demo limit reached",
                    "message": f"Du har använt alla {DEMO_QUERY_LIMIT} gratis demo-frågor. Skapa ett gratis konto för att fortsätta!",
                    "demo_mode": True,
                    "queries_used": demo_count,
                    "queries_limit": DEMO_QUERY_LIMIT,
                    "signup_url": "/login"
                }
            )

        # Increment demo counter (keyed on hashed IP, raw IP never stored)
        increment_demo_query(db, request.sessionId, ip_key)

        logger.info(f"Demo query ({demo_count + 1}/{DEMO_QUERY_LIMIT})")

        # Demo users can only ask general questions, not analytics queries
        answer = await call_deepseek_api(request.message)

        return ChatResponse(
            answer=answer + f"\n\n_💡 Demo mode: {demo_count + 1}/{DEMO_QUERY_LIMIT} frågor använda. [Skapa gratis konto](/login) för obegränsad access!_",
            logId=log_id,
            timestamp=datetime.utcnow().isoformat()
        )

    # Authenticated user flow
    logger.info(f"Chat request from {current_user.email}: {request.message[:50]}")

    # Check AI quota before processing
    if not check_ai_quota(db, current_user, "chatbot"):
        quota_info = get_quota_info(current_user)
        upgrade_msg = get_upgrade_message(current_user)

        logger.warning(f"AI quota exceeded for user {current_user.email}")

        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "AI quota exceeded",
                "message": f"You've used {quota_info['used']}/{quota_info['quota']} AI messages this month. {upgrade_msg}",
                "quota_info": quota_info,
                "upgrade_url": "/billing"
            }
        )

    # Check if this is an analytics query
    conv_analytics = ConversationalAnalyticsService(db)

    if conv_analytics.is_analytics_query(request.message):
        # Extract website_id from context
        website_id = conv_analytics.extract_website_from_context(request.context)

        # Verify the authenticated user actually owns/has access to the
        # client-supplied website_id before querying it (cross-tenant IDOR).
        from app.services.website_service import WebsiteService
        owns_website = website_id and WebsiteService(db).get_website_by_id(website_id, current_user.email)

        if website_id and not owns_website:
            logger.warning(f"Chatbot website access denied for {current_user.email} -> website {website_id}")
            answer = "Du har inte åtkomst till den här webbplatsen."
        elif website_id:
            try:
                # Process analytics query
                answer = await conv_analytics.process_analytics_query(
                    message=request.message,
                    website_id=website_id,
                    user_email=current_user.email
                )
                logger.info(f"Answered analytics query for user {current_user.email}")
            except Exception as e:
                logger.error(f"Analytics query error: {e}")
                answer = f"Kunde inte hämta analytics data. Försök igen senare."
        else:
            answer = "För att svara på analytics-frågor behöver jag veta vilken website du vill analysera. Välj en website först."
    else:
        # Regular chatbot response
        answer = await call_deepseek_api(request.message)

    # Increment usage counter after successful response
    increment_ai_usage(db, current_user, "chatbot")

    return ChatResponse(answer=answer, logId=log_id, timestamp=datetime.utcnow().isoformat())

@router.post("/feedback")
async def chat_feedback(feedback: FeedbackRequest):
    logger.info(f"Feedback: {'👍' if feedback.helpful else '👎'}")
    return {"status": "ok"}
