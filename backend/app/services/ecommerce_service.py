"""
E-commerce service for recording and retrieving revenue tracking data.

Handles the business logic for:
- Recording e-commerce events (purchases, cart actions, product views)
- Revenue analytics and statistics
- Product performance analytics
- Conversion funnel analysis
- Multi-currency revenue tracking
"""
import logging
from typing import Optional, Dict, List, Tuple
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, distinct, case
from sqlalchemy.exc import IntegrityError
from user_agents import parse

from app.config import settings
from app.models.ecommerce_event import EcommerceEvent
from app.models.website import Website
from app.utils.security import generate_visitor_hash

logger = logging.getLogger(__name__)


class EcommerceService:
    """
    Service for handling e-commerce tracking and analytics.

    This service manages revenue tracking and product analytics:
    1. Record e-commerce events (purchases, cart additions, product views)
    2. Generate revenue statistics
    3. Analyze product performance
    4. Calculate conversion funnels
    5. Track revenue over time

    Attributes:
        db: SQLAlchemy database session
    """

    def __init__(self, db: Session):
        """
        Initialize e-commerce service with database session.

        Args:
            db: SQLAlchemy database session for database operations
        """
        self.db = db
        logger.debug("EcommerceService initialized")

    def _generate_visitor_hash(self, ip_address: str, user_agent: str, website_domain: str) -> str:
        return generate_visitor_hash(ip_address, user_agent, website_domain)

    def _detect_device_type(self, user_agent: str) -> str:
        """
        Detect device type from User-Agent.

        Args:
            user_agent: User-Agent string

        Returns:
            str: Device type ('desktop', 'mobile', or 'tablet')
        """
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
        """
        Detect browser name from User-Agent string.

        Args:
            user_agent: User-Agent string

        Returns:
            str: Browser name
        """
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

    def _get_country_from_ip(self, ip_address: str) -> Optional[str]:
        """
        Get country code from IP address.

        Resolves country using ONLY a local MaxMind GeoLite2 database
        (settings.GEOIP_DB_PATH). No third-party network lookups are
        performed, so visitor IPs never leave this server. Returns None
        (country Unknown) when the DB is unconfigured or missing.

        Args:
            ip_address: IP address to lookup

        Returns:
            Optional[str]: 2-letter country code or None
        """
        if ip_address.startswith(('127.', '10.', '192.168.', '172.16.', '::1', 'localhost')):
            logger.debug(f"Skipping GeoIP lookup for local IP: {ip_address}")
            return None

        db_path = settings.GEOIP_DB_PATH
        if not db_path:
            return None

        # Resolve country from the local GeoLite2 database only.
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

    def record_ecommerce_event(
        self,
        tracking_code: str,
        event_type: str,
        event_name: str,
        ip_address: str,
        user_agent: str,
        transaction_id: Optional[str] = None,
        revenue: Optional[Decimal] = None,
        currency: str = "USD",
        tax: Optional[Decimal] = None,
        shipping: Optional[Decimal] = None,
        product_id: Optional[str] = None,
        product_name: Optional[str] = None,
        product_category: Optional[str] = None,
        product_brand: Optional[str] = None,
        product_variant: Optional[str] = None,
        quantity: int = 1,
        price: Optional[Decimal] = None,
        properties: Optional[Dict] = None,
        utm_source: Optional[str] = None,
        utm_medium: Optional[str] = None,
        utm_campaign: Optional[str] = None,
        utm_content: Optional[str] = None,
        utm_term: Optional[str] = None
    ) -> Tuple[bool, str, Optional[int]]:
        """
        Record an e-commerce event.

        Args:
            tracking_code: Website tracking code
            event_type: Type of e-commerce event
            event_name: Custom event name
            ip_address: Visitor's IP address
            user_agent: Visitor's User-Agent string
            transaction_id: Transaction ID (for purchases)
            revenue: Transaction revenue
            currency: ISO 4217 currency code
            tax: Tax amount
            shipping: Shipping cost
            product_id: Product SKU or ID
            product_name: Product name
            product_category: Product category
            product_brand: Product brand
            product_variant: Product variant
            quantity: Product quantity
            price: Product price
            properties: Additional custom properties
            utm_source: UTM source
            utm_medium: UTM medium
            utm_campaign: UTM campaign
            utm_content: UTM content
            utm_term: UTM term

        Returns:
            Tuple[bool, str, Optional[int]]: (success, message, event_id)
        """
        logger.info(f"Recording e-commerce event: tracking_code={tracking_code}, type={event_type}")

        try:
            # Validate tracking code and get website
            website = self.db.query(Website).filter(
                Website.tracking_code == tracking_code,
                Website.is_active == True
            ).first()

            if not website:
                logger.warning(f"Invalid or inactive tracking code: {tracking_code}")
                return False, "Invalid tracking code", None

            # Security check: Verify domain ownership
            if not website.is_verified:
                logger.warning(
                    f"🚫 Domain not verified for website {website.id} ({website.domain}). "
                    f"Blocking e-commerce tracking until owner verifies DNS record."
                )
                return False, "Domain not verified. Please verify domain ownership via DNS before tracking.", None

            # Generate visitor hash
            visitor_hash = self._generate_visitor_hash(ip_address, user_agent, website.domain)

            # Detect device type and browser
            device_type = self._detect_device_type(user_agent)
            browser = self._detect_browser(user_agent)

            # Get country from IP
            country = self._get_country_from_ip(ip_address)

            # Create e-commerce event record
            ecommerce_event = EcommerceEvent(
                website_id=website.id,
                event_type=event_type,
                event_name=event_name,
                transaction_id=transaction_id,
                revenue=revenue,
                currency=currency.upper(),
                tax=tax,
                shipping=shipping,
                product_id=product_id,
                product_name=product_name,
                product_category=product_category,
                product_brand=product_brand,
                product_variant=product_variant,
                quantity=quantity,
                price=price,
                properties=properties,
                visitor_hash=visitor_hash,
                country=country,
                device_type=device_type,
                browser=browser,
                timestamp=datetime.now(timezone.utc),
                utm_source=utm_source,
                utm_medium=utm_medium,
                utm_campaign=utm_campaign,
                utm_content=utm_content,
                utm_term=utm_term
            )

            self.db.add(ecommerce_event)
            try:
                self.db.commit()
            except IntegrityError as e:
                self.db.rollback()
                # ONLY a unique-violation on the idempotency index is a
                # legitimate duplicate; every other IntegrityError (check
                # constraints, FKs) is a real failure that must not be
                # reported as success — that silently drops revenue.
                pgcode = getattr(getattr(e, "orig", None), "pgcode", None)
                if pgcode == "23505":  # unique_violation
                    logger.info(
                        f"Duplicate purchase ignored: website_id={website.id}, "
                        f"transaction_id={transaction_id}"
                    )
                    return True, "Duplicate transaction ignored", None
                logger.error(f"E-commerce event integrity error: {e}")
                return False, "Invalid event data", None
            self.db.refresh(ecommerce_event)

            logger.info(
                f"E-commerce event recorded: website_id={website.id}, "
                f"type={event_type}, product={product_name}, revenue={revenue}"
            )
            return True, "E-commerce event recorded", ecommerce_event.id

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error recording e-commerce event: {e}", exc_info=True)
            return False, "Failed to record e-commerce event", None

    def resolve_currency(self, website_id: int, currency: Optional[str] = None) -> str:
        """Pick which currency's revenue to report.

        Revenue figures can't be summed across currencies, so every query is
        scoped to one. Defaulting that to USD meant a shop selling in SEK/EUR
        saw a permanent zero; instead, fall back to the currency this site
        actually records the most transactions in.
        """
        if currency:
            return currency.upper()

        row = self.db.query(
            EcommerceEvent.currency,
            func.count(EcommerceEvent.id).label('n')
        ).filter(
            EcommerceEvent.website_id == website_id,
            EcommerceEvent.event_type == 'purchase',
        ).group_by(EcommerceEvent.currency).order_by(func.count(EcommerceEvent.id).desc()).first()

        return row.currency if row else "USD"

    def get_revenue_stats(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime,
        currency: Optional[str] = None
    ) -> Dict:
        """
        Get revenue statistics for a date range.

        Args:
            website_id: Website ID
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            currency: Currency to report in; defaults to the site's most-used

        Returns:
            Dict: Revenue statistics
        """
        currency = self.resolve_currency(website_id, currency)
        logger.info(f"Getting revenue stats: website_id={website_id}, currency={currency}")

        try:
            # Query purchase events
            stats = self.db.query(
                func.sum(EcommerceEvent.revenue).label('total_revenue'),
                func.count(distinct(EcommerceEvent.transaction_id)).label('total_transactions'),
                func.sum(EcommerceEvent.tax).label('total_tax'),
                func.sum(EcommerceEvent.shipping).label('total_shipping'),
                func.count(distinct(EcommerceEvent.visitor_hash)).label('unique_customers')
            ).filter(
                and_(
                    EcommerceEvent.website_id == website_id,
                    EcommerceEvent.event_type == 'purchase',
                    EcommerceEvent.timestamp >= start_date,
                    EcommerceEvent.timestamp <= end_date,
                    EcommerceEvent.currency == currency.upper(),
                    EcommerceEvent.revenue.isnot(None)
                )
            ).first()

            total_revenue = float(stats.total_revenue) if stats.total_revenue else 0.0
            total_transactions = stats.total_transactions or 0
            total_tax = float(stats.total_tax) if stats.total_tax else 0.0
            total_shipping = float(stats.total_shipping) if stats.total_shipping else 0.0
            unique_customers = stats.unique_customers or 0

            # Calculate average order value
            average_order_value = total_revenue / total_transactions if total_transactions > 0 else 0.0

            result = {
                "total_revenue": Decimal(str(total_revenue)),
                "total_transactions": total_transactions,
                "average_order_value": Decimal(str(average_order_value)),
                "total_tax": Decimal(str(total_tax)),
                "total_shipping": Decimal(str(total_shipping)),
                "unique_customers": unique_customers,
                "currency": currency.upper()
            }

            logger.debug(f"Revenue stats: {total_revenue} {currency}, {total_transactions} transactions")
            return result

        except Exception as e:
            logger.error(f"Error getting revenue stats: {e}", exc_info=True)
            return {
                "total_revenue": Decimal("0"),
                "total_transactions": 0,
                "average_order_value": Decimal("0"),
                "total_tax": Decimal("0"),
                "total_shipping": Decimal("0"),
                "unique_customers": 0,
                "currency": currency.upper()
            }

    def get_top_products(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime,
        limit: int = 10
    ) -> Dict:
        """
        Get top selling products.

        Args:
            website_id: Website ID
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            limit: Maximum number of products to return

        Returns:
            Dict: Top products list
        """
        logger.info(f"Getting top products: website_id={website_id}")

        try:
            # Query purchase events grouped by product
            products = self.db.query(
                EcommerceEvent.product_id,
                EcommerceEvent.product_name,
                EcommerceEvent.product_category,
                func.sum(EcommerceEvent.quantity).label('units_sold'),
                func.sum(EcommerceEvent.revenue).label('total_revenue'),
                func.count(distinct(EcommerceEvent.visitor_hash)).label('unique_buyers')
            ).filter(
                and_(
                    EcommerceEvent.website_id == website_id,
                    EcommerceEvent.event_type == 'purchase',
                    EcommerceEvent.timestamp >= start_date,
                    EcommerceEvent.timestamp <= end_date,
                    EcommerceEvent.product_name.isnot(None)
                )
            ).group_by(
                EcommerceEvent.product_id,
                EcommerceEvent.product_name,
                EcommerceEvent.product_category
            ).order_by(
                func.sum(EcommerceEvent.revenue).desc()
            ).limit(limit).all()

            # Get total unique products
            total_products = self.db.query(
                func.count(distinct(EcommerceEvent.product_id))
            ).filter(
                and_(
                    EcommerceEvent.website_id == website_id,
                    EcommerceEvent.event_type == 'purchase',
                    EcommerceEvent.timestamp >= start_date,
                    EcommerceEvent.timestamp <= end_date,
                    EcommerceEvent.product_name.isnot(None)
                )
            ).scalar() or 0

            product_list = [
                {
                    "product_id": p.product_id,
                    "product_name": p.product_name,
                    "product_category": p.product_category,
                    "units_sold": p.units_sold or 0,
                    "total_revenue": Decimal(str(p.total_revenue)) if p.total_revenue else Decimal("0"),
                    "unique_buyers": p.unique_buyers or 0
                }
                for p in products
            ]

            result = {
                "products": product_list,
                "total_products": total_products
            }

            logger.debug(f"Found {len(product_list)} top products")
            return result

        except Exception as e:
            logger.error(f"Error getting top products: {e}", exc_info=True)
            return {
                "products": [],
                "total_products": 0
            }

    def get_conversion_funnel(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime
    ) -> Dict:
        """
        Get conversion funnel analysis.

        Analyzes the conversion funnel from product view to purchase:
        - view_item → add_to_cart → begin_checkout → purchase

        Args:
            website_id: Website ID
            start_date: Start date (inclusive)
            end_date: End date (inclusive)

        Returns:
            Dict: Conversion funnel statistics
        """
        logger.info(f"Getting conversion funnel: website_id={website_id}")

        try:
            base_conditions = [
                EcommerceEvent.website_id == website_id,
                EcommerceEvent.timestamp >= start_date,
                EcommerceEvent.timestamp <= end_date
            ]

            # Count unique visitors for each funnel stage
            viewed_products = self.db.query(
                func.count(distinct(EcommerceEvent.visitor_hash))
            ).filter(
                and_(*base_conditions, EcommerceEvent.event_type == 'view_item')
            ).scalar() or 0

            added_to_cart = self.db.query(
                func.count(distinct(EcommerceEvent.visitor_hash))
            ).filter(
                and_(*base_conditions, EcommerceEvent.event_type == 'add_to_cart')
            ).scalar() or 0

            started_checkout = self.db.query(
                func.count(distinct(EcommerceEvent.visitor_hash))
            ).filter(
                and_(*base_conditions, EcommerceEvent.event_type == 'begin_checkout')
            ).scalar() or 0

            completed_purchase = self.db.query(
                func.count(distinct(EcommerceEvent.visitor_hash))
            ).filter(
                and_(*base_conditions, EcommerceEvent.event_type == 'purchase')
            ).scalar() or 0

            # Calculate conversion rates
            cart_rate = (added_to_cart / viewed_products * 100) if viewed_products > 0 else 0.0
            checkout_rate = (started_checkout / added_to_cart * 100) if added_to_cart > 0 else 0.0
            purchase_rate = (completed_purchase / started_checkout * 100) if started_checkout > 0 else 0.0
            overall_conversion = (completed_purchase / viewed_products * 100) if viewed_products > 0 else 0.0

            result = {
                "viewed_products": viewed_products,
                "added_to_cart": added_to_cart,
                "cart_rate": round(cart_rate, 2),
                "started_checkout": started_checkout,
                "checkout_rate": round(checkout_rate, 2),
                "completed_purchase": completed_purchase,
                "purchase_rate": round(purchase_rate, 2),
                "overall_conversion": round(overall_conversion, 2)
            }

            logger.debug(f"Conversion funnel: {overall_conversion}% overall conversion")
            return result

        except Exception as e:
            logger.error(f"Error getting conversion funnel: {e}", exc_info=True)
            return {
                "viewed_products": 0,
                "added_to_cart": 0,
                "cart_rate": 0.0,
                "started_checkout": 0,
                "checkout_rate": 0.0,
                "completed_purchase": 0,
                "purchase_rate": 0.0,
                "overall_conversion": 0.0
            }

    def get_revenue_timeseries(
        self,
        website_id: int,
        start_date: datetime,
        end_date: datetime,
        currency: Optional[str] = None
    ) -> Dict:
        """
        Get revenue over time (timeseries data).

        Args:
            website_id: Website ID
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            currency: Filter by currency code

        Returns:
            Dict: Revenue timeseries data
        """
        currency = self.resolve_currency(website_id, currency)
        logger.info(f"Getting revenue timeseries: website_id={website_id}, currency={currency}")

        try:
            # Group by day
            results = self.db.query(
                func.date(EcommerceEvent.timestamp).label('date'),
                func.sum(EcommerceEvent.revenue).label('revenue'),
                func.count(distinct(EcommerceEvent.transaction_id)).label('transactions')
            ).filter(
                and_(
                    EcommerceEvent.website_id == website_id,
                    EcommerceEvent.event_type == 'purchase',
                    EcommerceEvent.timestamp >= start_date,
                    EcommerceEvent.timestamp <= end_date,
                    EcommerceEvent.currency == currency.upper(),
                    EcommerceEvent.revenue.isnot(None)
                )
            ).group_by(
                func.date(EcommerceEvent.timestamp)
            ).order_by(
                func.date(EcommerceEvent.timestamp)
            ).all()

            data = []
            total_revenue = Decimal("0")
            total_transactions = 0

            for row in results:
                revenue = Decimal(str(row.revenue)) if row.revenue else Decimal("0")
                transactions = row.transactions or 0
                avg_order_value = revenue / transactions if transactions > 0 else Decimal("0")

                data.append({
                    "date": row.date.isoformat(),
                    "revenue": revenue,
                    "transactions": transactions,
                    "average_order_value": avg_order_value
                })

                total_revenue += revenue
                total_transactions += transactions

            result = {
                "data": data,
                "total_revenue": total_revenue,
                "total_transactions": total_transactions
            }

            logger.debug(f"Revenue timeseries: {len(data)} data points")
            return result

        except Exception as e:
            logger.error(f"Error getting revenue timeseries: {e}", exc_info=True)
            return {
                "data": [],
                "total_revenue": Decimal("0"),
                "total_transactions": 0
            }
