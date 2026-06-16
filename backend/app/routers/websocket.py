"""
WebSocket router for real-time analytics updates.

Provides WebSocket endpoints for:
- Live pageview updates
- Real-time visitor counts
- Instant dashboard updates without polling
"""
import logging
import json
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.website import Website

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """
    Manages WebSocket connections for real-time updates.

    Handles:
    - Multiple concurrent connections per website
    - Broadcasting updates to all connected clients
    - Graceful disconnect handling
    """

    def __init__(self):
        """Initialize connection manager with empty connection pool."""
        # Store connections by website_id
        # Format: {website_id: {websocket1, websocket2, ...}}
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        logger.info("ConnectionManager initialized")

    async def connect(self, websocket: WebSocket, website_id: int):
        """
        Accept and register a new WebSocket connection.

        Args:
            websocket: WebSocket connection
            website_id: Website ID this connection is for
        """
        await websocket.accept()

        if website_id not in self.active_connections:
            self.active_connections[website_id] = set()

        self.active_connections[website_id].add(websocket)
        logger.info(f"WebSocket connected: website_id={website_id}, total={len(self.active_connections[website_id])}")

    def disconnect(self, websocket: WebSocket, website_id: int):
        """
        Remove a WebSocket connection.

        Args:
            websocket: WebSocket connection to remove
            website_id: Website ID
        """
        if website_id in self.active_connections:
            self.active_connections[website_id].discard(websocket)

            # Clean up empty sets
            if not self.active_connections[website_id]:
                del self.active_connections[website_id]

            logger.info(f"WebSocket disconnected: website_id={website_id}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        """
        Send a message to a specific WebSocket connection.

        Args:
            message: JSON string message
            websocket: WebSocket connection
        """
        try:
            await websocket.send_text(message)
        except Exception as e:
            logger.error(f"Error sending personal message: {e}")

    async def broadcast_to_website(self, message: dict, website_id: int):
        """
        Broadcast a message to all connections for a website.

        Args:
            message: Message dict (will be JSON encoded)
            website_id: Website ID to broadcast to
        """
        if website_id not in self.active_connections:
            logger.debug(f"No active connections for website_id={website_id}")
            return

        message_json = json.dumps(message)
        disconnected = set()

        for connection in self.active_connections[website_id]:
            try:
                await connection.send_text(message_json)
            except Exception as e:
                logger.error(f"Error broadcasting to connection: {e}")
                disconnected.add(connection)

        # Remove disconnected clients
        for connection in disconnected:
            self.disconnect(connection, website_id)

        logger.debug(f"Broadcast to {len(self.active_connections.get(website_id, set()))} connections: website_id={website_id}")

    def get_connection_count(self, website_id: int) -> int:
        """
        Get number of active connections for a website.

        Args:
            website_id: Website ID

        Returns:
            Number of active connections
        """
        return len(self.active_connections.get(website_id, set()))


# Global connection manager instance
manager = ConnectionManager()


@router.websocket("/ws/live/{website_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    website_id: int,
    tracking_code: str = Query(..., description="Website tracking code for authentication"),
    db: Session = Depends(get_db)
):
    """
    WebSocket endpoint for real-time analytics updates.

    Authenticates using tracking code and provides live updates when
    new pageviews are recorded.

    Args:
        websocket: WebSocket connection
        website_id: Website ID
        tracking_code: Website tracking code (for authentication)
        db: Database session

    Message Format (sent to client):
        {
            "type": "pageview",
            "data": {
                "path": "/blog/post-1",
                "country": "SE",
                "device": "desktop",
                "timestamp": "2024-01-01T12:00:00Z"
            }
        }

        {
            "type": "visitor_count",
            "data": {
                "current_visitors": 5
            }
        }
    """
    logger.info(f"WebSocket connection attempt: website_id={website_id}")

    # Authenticate using tracking code
    website = db.query(Website).filter(
        Website.id == website_id,
        Website.tracking_code == tracking_code,
        Website.is_active == True
    ).first()

    if not website:
        logger.warning(f"WebSocket auth failed: invalid tracking code for website_id={website_id}")
        await websocket.close(code=4001, reason="Invalid tracking code")
        return

    # Accept connection
    await manager.connect(websocket, website_id)

    try:
        # Send initial connection confirmation
        await manager.send_personal_message(
            json.dumps({
                "type": "connected",
                "data": {
                    "website_id": website_id,
                    "message": "Real-time updates enabled"
                }
            }),
            websocket
        )

        # Keep connection alive and listen for client messages
        while True:
            # Wait for messages from client (e.g., ping/pong)
            data = await websocket.receive_text()

            # Handle client messages
            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    await manager.send_personal_message(
                        json.dumps({"type": "pong"}),
                        websocket
                    )
            except json.JSONDecodeError:
                logger.warning("Invalid JSON received from WebSocket client")

    except WebSocketDisconnect:
        manager.disconnect(websocket, website_id)
        logger.info(f"WebSocket client disconnected: website_id={website_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        manager.disconnect(websocket, website_id)


# Helper function to broadcast pageview updates
# This will be called from analytics router when a pageview is recorded
async def broadcast_pageview(website_id: int, pageview_data: dict):
    """
    Broadcast a new pageview to all connected WebSocket clients.

    Args:
        website_id: Website ID
        pageview_data: Pageview information dict
    """
    message = {
        "type": "pageview",
        "data": pageview_data
    }
    await manager.broadcast_to_website(message, website_id)


async def broadcast_visitor_count(website_id: int, count: int):
    """
    Broadcast updated visitor count to all connected WebSocket clients.

    Args:
        website_id: Website ID
        count: Current visitor count
    """
    message = {
        "type": "visitor_count",
        "data": {
            "current_visitors": count
        }
    }
    await manager.broadcast_to_website(message, website_id)


# Debug mode manager (separate from production WebSocket)
class DebugConnectionManager(ConnectionManager):
    """
    Manages WebSocket connections for debug mode.

    Debug mode provides detailed tracking information for developers
    without polluting production analytics.
    """

    def __init__(self):
        super().__init__()
        logger.info("DebugConnectionManager initialized")


# Global debug manager instance
debug_manager = DebugConnectionManager()


@router.websocket("/ws/debug/{website_id}")
async def debug_websocket_endpoint(
    websocket: WebSocket,
    website_id: int,
    token: str = Query(None, description="Owner session token for authentication"),
    api_token: str = Query(None, description="API token for authentication"),
    db: Session = Depends(get_db)
):
    """
    WebSocket endpoint for Live Debug Mode.

    Provides real-time detailed tracking information for debugging:
    - All tracking events (including debug-flagged ones)
    - Request metadata (anonymized IP, browser/device family)
    - Parameter validation results
    - Bot detection results
    - GeoIP data

    Authentication: requires the owner's session token (?token=) OR an API
    token (?api_token=) with access to the website. The public tracking_code
    must NOT grant access here, as it is embedded in every customer's page.

    Args:
        websocket: WebSocket connection
        website_id: Website ID
        token: Owner session token (Bearer session) for authentication
        api_token: API token for authentication
        db: Database session

    Message Format (sent to client):
        {
            "type": "debug_event",
            "data": {
                "timestamp": "2025-11-01T12:00:00Z",
                "event_type": "pageview",
                "path": "/test",
                "is_debug": true,
                "metadata": {
                    "ip": "192.168.1.1",
                    "user_agent": "Mozilla/5.0...",
                    "referrer": "https://google.com",
                    "country": "SE",
                    "device": "desktop",
                    "browser": "Chrome",
                    "screen_width": 1920,
                    "utm_source": "google",
                    "utm_medium": "cpc"
                },
                "validation": {
                    "is_bot": false,
                    "dnt_header": false,
                    "tracking_code_valid": true
                }
            }
        }
    """
    logger.info(f"Debug WebSocket connection attempt: website_id={website_id}")

    # Authenticate the dashboard owner/member (NOT the public tracking_code).
    # The debug stream exposes request metadata, so it must be gated behind a
    # session token or API token belonging to someone with access.
    from app.services.auth_service import AuthService
    from app.services.team_service import TeamService
    from app.services.token_service import TokenService

    user_email = None

    if api_token:
        api_website = TokenService(db).validate_token(api_token)
        if api_website and api_website.id == website_id:
            user_email = api_website.user_email
    elif token:
        user = AuthService(db).validate_session(token)
        if user:
            user_email = user.email

    if not user_email:
        logger.warning(f"Debug WebSocket auth failed: missing/invalid credentials for website_id={website_id}")
        await websocket.close(code=4001, reason="Authentication required")
        return

    # Verify the authenticated user actually has access to this website
    role = TeamService(db).check_website_access(user_email, website_id)
    if not role:
        logger.warning(f"Debug WebSocket auth failed: {user_email} has no access to website_id={website_id}")
        await websocket.close(code=4003, reason="Access denied")
        return

    website = db.query(Website).filter(
        Website.id == website_id,
        Website.is_active == True
    ).first()

    if not website:
        logger.warning(f"Debug WebSocket auth failed: website {website_id} not found or inactive")
        await websocket.close(code=4001, reason="Website not found")
        return

    # Accept connection
    await debug_manager.connect(websocket, website_id)

    try:
        # Send initial connection confirmation
        await debug_manager.send_personal_message(
            json.dumps({
                "type": "debug_connected",
                "data": {
                    "website_id": website_id,
                    "domain": website.domain,
                    "message": "Live Debug Mode enabled - all tracking events will appear here",
                    "note": "Debug-flagged events will NOT be recorded in production analytics"
                }
            }),
            websocket
        )

        # Keep connection alive
        while True:
            data = await websocket.receive_text()

            # Handle ping/pong
            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    await debug_manager.send_personal_message(
                        json.dumps({"type": "pong"}),
                        websocket
                    )
            except json.JSONDecodeError:
                logger.warning("Invalid JSON received from debug WebSocket client")

    except WebSocketDisconnect:
        debug_manager.disconnect(websocket, website_id)
        logger.info(f"Debug WebSocket client disconnected: website_id={website_id}")
    except Exception as e:
        logger.error(f"Debug WebSocket error: {e}", exc_info=True)
        debug_manager.disconnect(websocket, website_id)


async def broadcast_debug_event(website_id: int, debug_data: dict):
    """
    Broadcast a tracking event to debug WebSocket clients.

    Args:
        website_id: Website ID
        debug_data: Detailed debug information dict
    """
    message = {
        "type": "debug_event",
        "data": debug_data
    }
    await debug_manager.broadcast_to_website(message, website_id)
