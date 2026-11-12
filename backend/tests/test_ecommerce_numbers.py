"""The e-commerce figures add up: refunds, currencies and country.

Each of these was a number a shop owner would notice only by comparing the
dashboard with their own books. They are written against the service so the
arithmetic is the subject and not the HTTP plumbing.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services.ecommerce_service import EcommerceService

BROWSER = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"


def _record(db, website, event_type, revenue, currency="SEK", product=None,
            ip="8.8.8.8", quantity=1):
    ok, message, _ = EcommerceService(db).record_ecommerce_event(
        tracking_code=website["tracking_code"],
        event_type=event_type,
        event_name=event_type,
        ip_address=ip,
        user_agent=BROWSER,
        transaction_id=f"{event_type}-{uuid.uuid4().hex[:10]}",
        revenue=Decimal(str(revenue)),
        currency=currency,
        product_id=product,
        product_name=product,
        quantity=quantity,
    )
    assert ok, message


def _window():
    now = datetime.now(timezone.utc)
    return now - timedelta(days=1), now + timedelta(days=1)


class TestRefundsReduceRevenue:
    def test_the_total_is_net_of_refunds(self, db, website):
        _record(db, website, "purchase", 1000)
        _record(db, website, "purchase", 500)
        _record(db, website, "refund", 300)

        start, end = _window()
        stats = EcommerceService(db).get_revenue_stats(website["id"], start, end, "SEK")

        assert stats["total_revenue"] == Decimal("1200")

    def test_a_refund_is_not_an_order(self, db, website):
        """Two purchases and a refund is still two orders, worth 600 each."""
        _record(db, website, "purchase", 600)
        _record(db, website, "purchase", 600)
        _record(db, website, "refund", 600)

        start, end = _window()
        stats = EcommerceService(db).get_revenue_stats(website["id"], start, end, "SEK")

        assert stats["total_transactions"] == 2
        assert stats["average_order_value"] == Decimal("600")

    def test_a_refund_in_another_currency_stays_out(self, db, website):
        _record(db, website, "purchase", 1000, currency="SEK")
        _record(db, website, "refund", 400, currency="EUR")

        start, end = _window()
        stats = EcommerceService(db).get_revenue_stats(website["id"], start, end, "SEK")

        assert stats["total_revenue"] == Decimal("1000")

    def test_the_chart_agrees_with_the_total(self, db, website):
        _record(db, website, "purchase", 1000)
        _record(db, website, "refund", 250)

        start, end = _window()
        series = EcommerceService(db).get_revenue_timeseries(website["id"], start, end, "SEK")

        assert series["total_revenue"] == 750.0
        assert series["total_transactions"] == 1


class TestTopProductsStayInOneCurrency:
    def test_other_currencies_are_not_added_in(self, db, website):
        _record(db, website, "purchase", 1000, currency="SEK", product="Lamp")
        _record(db, website, "purchase", 40, currency="EUR", product="Lamp")

        start, end = _window()
        top = EcommerceService(db).get_top_products(
            website["id"], start, end, currency="SEK"
        )

        assert len(top["products"]) == 1
        assert top["products"][0]["total_revenue"] == Decimal("1000")
        assert top["products"][0]["units_sold"] == 1

    def test_without_a_currency_it_follows_the_headline_figure(self, db, website):
        """Same default as the totals: the currency the site sells in most."""
        _record(db, website, "purchase", 1000, currency="SEK", product="Lamp")
        _record(db, website, "purchase", 900, currency="SEK", product="Lamp")
        _record(db, website, "purchase", 40, currency="EUR", product="Lamp")

        start, end = _window()
        top = EcommerceService(db).get_top_products(website["id"], start, end)

        assert top["products"][0]["total_revenue"] == Decimal("1900")


class TestCountryUsesTheSharedLookup:
    @pytest.fixture
    def swedish_range(self, db):
        db.execute(
            text(
                "INSERT INTO ip_country_ranges (start_ip, end_ip, country, registry) "
                "VALUES ('2.0.0.0', '2.1.255.255', 'SE', 'ripencc')"
            )
        )
        db.commit()

    def test_the_registry_table_answers_when_there_is_no_mmdb(
        self, db, website, swedish_range, monkeypatch
    ):
        """Without a GeoIP file the country was always NULL here, while
        pageviews on the same site resolved from the registry table."""
        from app.config import settings

        monkeypatch.setattr(settings, "GEOIP_DB_PATH", "")
        _record(db, website, "purchase", 100, ip="2.0.55.9")

        country = db.execute(
            text("SELECT country FROM ecommerce_events WHERE website_id = :w"),
            {"w": website["id"]},
        ).scalar()
        assert country == "SE"

    def test_a_private_address_is_still_unknown(self, db, website, swedish_range):
        _record(db, website, "purchase", 100, ip="192.168.1.20")

        country = db.execute(
            text("SELECT country FROM ecommerce_events WHERE website_id = :w"),
            {"w": website["id"]},
        ).scalar()
        assert country is None
