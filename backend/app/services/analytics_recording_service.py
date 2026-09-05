"""
Analytics recording service for tracking pageviews and custom events.

Handles visitor hashing, device/browser detection, GeoIP lookup, and
writing pageview/event records to the database.
"""
import logging
from typing import Optional, Dict, Tuple
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, urlencode
from sqlalchemy import text
from sqlalchemy.orm import Session
from user_agents import parse

from fastapi import HTTPException

from app.config import settings
from app.models.pageview import Pageview
from app.models.website import Website
from app.models.user import User
from app.models.custom_event import CustomEvent
from app.models.funnel import Funnel, FunnelEvent
from app.utils.security import generate_visitor_hash
from app.services.website_lookup import resolve_tracking_code
from app.services.usage_service import LIMIT_MESSAGE, may_record

logger = logging.getLogger(__name__)

SENSITIVE_PARAMS = frozenset({
    'token', 'key', 'secret', 'password', 'pwd', 'passwd',
    'auth', 'session', 'sid', 'code', 'api_key', 'apikey',
    'access_token', 'refresh_token', 'private_token', 'nonce',
    'signature', 'sig', 'credential', 'otp', 'email', 'mail', 'hash',
})


def sanitize_path(path: str) -> str:
    """Strip sensitive query parameters from a tracked path."""
    if '?' not in path:
        return path
    base, _, query = path.partition('?')
    params = parse_qs(query, keep_blank_values=True)
    cleaned = {k: v for k, v in params.items() if k.lower() not in SENSITIVE_PARAMS}
    if not cleaned:
        return base
    return base + '?' + urlencode(cleaned, doseq=True)


class AnalyticsRecordingService:
    """Service for recording pageviews and custom events."""

    def __init__(self, db: Session):
        self.db = db


    def complete_scroll_depth(
        self,
        tracking_code: str,
        path: str,
        depth: int,
        ip_address: str,
        user_agent: str,
    ) -> Tuple[bool, str]:
        """Fill in how far down the visitor read, on a pageview already written.

        The depth is only known when the visitor leaves, and the row has
        existed since the page loaded. This completes it rather than recording
        anything new, so it costs nothing against the monthly limit: the visit
        was already counted.

        The row is found by recomputing the visitor hash from this request,
        exactly as record_pageview computes it. That keeps the browser from
        having to hold a row id and from learning anything it did not already
        know: the hash is derived on the server from the address and the user
        agent it is already sending.

        Only ever increases the value. A page left and returned to would
        otherwise report the second, shallower visit.
        """
        website = resolve_tracking_code(self.db, tracking_code)
        if website is None or not website.is_active or not website.is_verified:
            return False, "Invalid tracking code"

        if depth is None or depth < 1 or depth > 100:
            return False, "Scroll depth must be between 1 and 100"

        visitor_hash = self._generate_visitor_hash(ip_address, user_agent, website.domain)

        # Through a SECURITY DEFINER function, the same way this schema
        # resolves a tracking code, a share token or an invitation. An UPDATE
        # policy for the tracking context looks like the direct route and is
        # not: Postgres fetches the rows to evaluate the WHERE clause, that
        # fetch is governed by SELECT policies, and the tracking context has
        # none on purpose. The update would match nothing while every security
        # test still passed.
        #
        # The function decides what may change rather than the caller: one
        # row, this website, this visitor, this path, within thirty minutes,
        # and only upward.
        updated = self.db.execute(
            text(
                "SELECT argus_complete_scroll_depth(:w, :h, :p, :depth)"
            ),
            {"depth": depth, "w": website.id, "h": visitor_hash, "p": path},
        ).scalar()
        self.db.commit()

        # Nothing matched is not a failure. The visit may have aged out, or a
        # deeper value may already be recorded, and neither is worth an error
        # in a browser that is in the middle of navigating away.
        if updated:
            logger.debug(f"Scroll depth {depth} recorded for website {website.id}")
        return True, "Recorded"

    def _generate_visitor_hash(self, ip_address: str, user_agent: str, website_domain: str) -> str:
        return generate_visitor_hash(ip_address, user_agent, website_domain)

    def _detect_device_type(self, screen_width: Optional[int], user_agent: str) -> str:
        """Detect device type from screen width and User-Agent."""
        if screen_width is not None:
            if screen_width < 768:
                return "mobile"
            elif screen_width < 1024:
                return "tablet"
            else:
                return "desktop"

        try:
            ua = parse(user_agent)
            if ua.is_mobile:
                return "mobile"
            elif ua.is_tablet:
                return "tablet"
            else:
                return "desktop"
        except Exception as e:
            logger.warning(f"Failed to parse User-Agent: {e}")
            return "desktop"

    def _detect_browser(self, user_agent: str) -> str:
        """Detect browser name from User-Agent string."""
        try:
            ua = parse(user_agent)
            browser = ua.browser.family

            if "Chrome" in browser:
                return "Chrome"
            elif "Firefox" in browser:
                return "Firefox"
            elif "Safari" in browser:
                return "Safari"
            elif "Edge" in browser:
                return "Edge"
            elif "Opera" in browser:
                return "Opera"
            else:
                return browser if browser else "Unknown"

        except Exception as e:
            logger.warning(f"Failed to detect browser: {e}")
            return "Unknown"

    def _categorize_channel(self, referrer: Optional[str], utm_medium: Optional[str]) -> str:
        """Categorize traffic source into channels."""
        if utm_medium:
            utm_medium_lower = utm_medium.lower()
            if utm_medium_lower == 'email':
                return "Email"
            elif utm_medium_lower in ['cpc', 'ppc', 'paid']:
                return "Paid"

        if not referrer or referrer == '' or referrer == '(Direct)':
            return "Direct"

        try:
            referrer_lower = referrer.lower()

            organic_domains = [
                'google.com', 'google.', 'bing.com', 'yahoo.com',
                'duckduckgo.com', 'search.yahoo.com', 'baidu.com',
                'yandex.com', 'ask.com'
            ]
            for domain in organic_domains:
                if domain in referrer_lower:
                    return "Organic Search"

            social_domains = [
                'facebook.com', 'fb.com', 'twitter.com', 't.co',
                'linkedin.com', 'instagram.com', 'reddit.com',
                'pinterest.com', 'tiktok.com', 'snapchat.com',
                'youtube.com', 'vimeo.com'
            ]
            for domain in social_domains:
                if domain in referrer_lower:
                    return "Social"

            return "Referral"

        except Exception as e:
            logger.warning(f"Error categorizing channel: {e}")
            return "Referral"

    def _get_country_from_ip(self, ip_address: str) -> Optional[str]:
        """Get country code from IP address.

        Resolves country using ONLY a local MaxMind GeoLite2 database
        (settings.GEOIP_DB_PATH). No third-party network lookups are
        performed, so visitor IPs never leave this server. Returns None
        (country Unknown) when the DB is unconfigured or missing.
        """
        if ip_address.startswith(('127.', '10.', '192.168.', '172.16.', '::1', 'localhost')):
            logger.debug(f"Skipping GeoIP lookup for local IP: {ip_address}")
            return None

        db_path = settings.GEOIP_DB_PATH
        if not db_path:
            return None

        try:
            import os
            import geoip2.database

            if not os.path.exists(db_path):
                logger.debug(f"GeoIP DB not found at {db_path}; skipping lookup")
                return None

            with geoip2.database.Reader(db_path) as reader:
                response = reader.country(ip_address)
                country_code = response.country.iso_code
                logger.debug(f"GeoIP lookup: {ip_address} -> {country_code}")
                return country_code
        except Exception:
            return None

    def record_pageview(
        self,
        tracking_code: str,
        path: str,
        referrer: Optional[str],
        screen_width: Optional[int],
        ip_address: str,
        user_agent: str,
        utm_source: Optional[str] = None,
        utm_medium: Optional[str] = None,
        utm_campaign: Optional[str] = None,
        utm_content: Optional[str] = None,
        utm_term: Optional[str] = None,
        screen_height: Optional[int] = None,
        scroll_depth: Optional[int] = None,
        properties: Optional[Dict] = None
    ) -> Tuple[bool, str]:
        """Record a new pageview."""
        path = sanitize_path(path)
        logger.info(f"Recording pageview: tracking_code={tracking_code}, path={path}")

        try:
            # Resolved through a SECURITY DEFINER function, so the tracking
            # context needs no read access to websites at all. See
            # app/services/website_lookup.py.
            website = resolve_tracking_code(self.db, tracking_code)
            if website and not website.is_active:
                website = None

            if not website:
                logger.warning(f"Invalid or inactive tracking code: {tracking_code}")
                return False, "Invalid tracking code"


            # Per-account monthly limit. Checked after resolving so an invalid
            # code and a full account are reported differently, and before
            # writing so a refused event costs nothing.
            if not may_record(self.db, website.owner_email):
                return False, LIMIT_MESSAGE

            if not website.is_verified:
                logger.warning(
                    f"Domain not verified for website {website.id} ({website.domain}). "
                    f"Blocking tracking until owner verifies DNS record."
                )
                return False, "Domain not verified. Please verify domain ownership via DNS before tracking."

            visitor_hash = self._generate_visitor_hash(ip_address, user_agent, website.domain)
            device_type = self._detect_device_type(screen_width, user_agent)
            browser = self._detect_browser(user_agent)
            country = self._get_country_from_ip(ip_address)

            pageview = Pageview(
                website_id=website.id,
                path=path,
                referrer=referrer if referrer else None,
                country=country,
                device_type=device_type,
                browser=browser,
                visitor_hash=visitor_hash,
                timestamp=datetime.now(timezone.utc),
                utm_source=utm_source,
                utm_medium=utm_medium,
                utm_campaign=utm_campaign,
                utm_content=utm_content,
                utm_term=utm_term,
                screen_width=screen_width,
                screen_height=screen_height,
                scroll_depth=scroll_depth,
                properties=properties
            )

            self.db.add(pageview)
            self._record_funnel_steps(website.id, path, visitor_hash)
            self.db.commit()

            logger.info(
                f"Pageview recorded: website_id={website.id}, "
                f"path={path}, device={device_type}, browser={browser}"
            )
            return True, "Pageview recorded"

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error recording pageview: {e}", exc_info=True)
            return False, "Failed to record pageview"

    def _record_funnel_steps(self, website_id: int, path: str, visitor_hash: str) -> None:
        """
        Record funnel progress for a pageview.

        Funnels are defined as a list of {step, name, path} entries; a visitor
        reaching one of those paths counts as reaching that step. This is the
        write side of the funnel feature — without it, funnel_events stays
        empty and every funnel reports 0% forever (which is exactly what it
        did before this existed).

        Only one row is kept per (funnel, visitor, step): the stats query
        counts distinct visitors, so repeat visits to the same step add
        nothing but table bloat.

        Runs inside the caller's transaction (committed with the pageview),
        but never propagates: a funnel problem must not cost us the pageview.
        """
        try:
            funnels = self.db.query(Funnel).filter(
                Funnel.website_id == website_id,
                Funnel.is_active == True
            ).all()

            for funnel in funnels:
                steps = funnel.steps or []
                for step in steps:
                    if step.get("path") != path:
                        continue

                    step_number = step.get("step")
                    already_recorded = self.db.query(FunnelEvent.id).filter(
                        FunnelEvent.funnel_id == funnel.id,
                        FunnelEvent.visitor_id == visitor_hash,
                        FunnelEvent.step_number == step_number
                    ).first()
                    if already_recorded:
                        continue

                    self.db.add(FunnelEvent(
                        funnel_id=funnel.id,
                        visitor_id=visitor_hash,
                        step_number=step_number,
                        step_name=step.get("name") or f"Step {step_number}",
                        path=path,
                        timestamp=datetime.now(timezone.utc),
                        # Last step reached = this visitor completed the funnel.
                        completed=step_number == max(
                            (s.get("step") or 0) for s in steps
                        ),
                    ))
                    logger.info(
                        f"Funnel step recorded: funnel_id={funnel.id}, "
                        f"step={step_number}, path={path}"
                    )
        except Exception as e:
            logger.error(f"Error recording funnel steps: {e}", exc_info=True)

    def record_custom_event(
        self,
        tracking_code: str,
        event_name: str,
        properties: Optional[Dict],
        ip_address: str,
        user_agent: str
    ) -> Tuple[bool, str]:
        """Record a custom event with optional properties."""
        logger.info(f"Recording custom event: tracking_code={tracking_code}, event={event_name}")

        try:
            # Resolved through a SECURITY DEFINER function, so the tracking
            # context needs no read access to websites at all. See
            # app/services/website_lookup.py.
            website = resolve_tracking_code(self.db, tracking_code)
            if website and not website.is_active:
                website = None

            if not website:
                logger.warning(f"Invalid tracking code: {tracking_code}")
                return False, "Invalid tracking code"


            # Per-account monthly limit. Checked after resolving so an invalid
            # code and a full account are reported differently, and before
            # writing so a refused event costs nothing.
            if not may_record(self.db, website.owner_email):
                return False, LIMIT_MESSAGE

            if not website.is_verified:
                logger.warning(
                    f"Domain not verified for website {website.id} ({website.domain}). "
                    f"Blocking custom event tracking."
                )
                return False, "Domain not verified"

            visitor_hash = self._generate_visitor_hash(ip_address, user_agent, website.domain)
            device_type = self._detect_device_type(None, user_agent)
            browser = self._detect_browser(user_agent)
            country = self._get_country_from_ip(ip_address)

            path = properties.get('path') if properties else None
            referrer = properties.get('referrer') if properties else None

            custom_event = CustomEvent(
                website_id=website.id,
                event_name=event_name,
                properties=properties,
                path=path,
                referrer=referrer,
                country=country,
                device_type=device_type,
                browser=browser,
                visitor_hash=visitor_hash,
                timestamp=datetime.now(timezone.utc)
            )

            self.db.add(custom_event)
            self.db.commit()

            logger.info(f"Custom event recorded: website_id={website.id}, event={event_name}")
            return True, "Event recorded"

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error recording custom event: {e}", exc_info=True)
            return False, "Failed to record event"
