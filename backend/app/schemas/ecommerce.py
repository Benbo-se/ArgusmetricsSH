"""
Pydantic schemas for e-commerce tracking endpoints.
"""
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal


class EcommerceEventRequest(BaseModel):
    """
    Request schema for tracking e-commerce events.

    Supports various e-commerce events:
    - view_item: Product page view
    - add_to_cart: Add product to cart
    - remove_from_cart: Remove from cart
    - begin_checkout: Start checkout process
    - add_payment_info: Payment info added
    - add_shipping_info: Shipping info added
    - purchase: Completed purchase
    - refund: Refund processed
    """
    tracking_code: str = Field(
        ...,
        description="Website tracking code",
        min_length=8,
        max_length=8,
        example="a1b2c3d4"
    )

    event_type: str = Field(
        ...,
        description="Type of e-commerce event",
        example="purchase"
    )

    event_name: Optional[str] = Field(
        None,
        description="Custom event name",
        max_length=255,
        example="Product Purchase"
    )

    # Transaction details (required for purchase events)
    transaction_id: Optional[str] = Field(
        None,
        description="Unique transaction identifier",
        max_length=255,
        example="ORDER-2025-001"
    )

    # Revenue data. Upper bound matters: tracking codes are public, so one
    # spoofed event with revenue=9e15 would wreck every revenue chart.
    revenue: Optional[Decimal] = Field(
        None,
        description="Transaction revenue",
        ge=0,
        le=100_000_000,
        example=99.99
    )

    currency: str = Field(
        default="USD",
        description="ISO 4217 currency code",
        min_length=3,
        max_length=3,
        example="USD"
    )

    tax: Optional[Decimal] = Field(
        None,
        description="Tax amount",
        ge=0,
        example=8.00
    )

    shipping: Optional[Decimal] = Field(
        None,
        description="Shipping cost",
        ge=0,
        example=5.99
    )

    # Product details
    product_id: Optional[str] = Field(
        None,
        description="Product SKU or ID",
        max_length=255,
        example="SKU-12345"
    )

    product_name: Optional[str] = Field(
        None,
        description="Product name",
        max_length=500,
        example="Premium Analytics Dashboard"
    )

    product_category: Optional[str] = Field(
        None,
        description="Product category",
        max_length=255,
        example="Software/Analytics"
    )

    product_brand: Optional[str] = Field(
        None,
        description="Product brand",
        max_length=255,
        example="Argusmetrics"
    )

    product_variant: Optional[str] = Field(
        None,
        description="Product variant (size, color, etc.)",
        max_length=255,
        example="Pro Plan"
    )

    quantity: int = Field(
        default=1,
        description="Product quantity",
        ge=1,
        example=1
    )

    price: Optional[Decimal] = Field(
        None,
        description="Product price per unit",
        ge=0,
        le=100_000_000,
        example=99.99
    )

    # Additional properties
    properties: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional custom properties",
        example={"payment_method": "credit_card", "coupon": "SAVE20"}
    )

    @field_validator("properties")
    @classmethod
    def _validate_properties(cls, v):
        """Same bounds as pageview/custom-event properties (was unvalidated)."""
        from app.schemas.analytics import validate_event_properties
        return validate_event_properties(v)

    # UTM parameters
    utm_source: Optional[str] = Field(None, max_length=255)
    utm_medium: Optional[str] = Field(None, max_length=255)
    utm_campaign: Optional[str] = Field(None, max_length=255)
    utm_content: Optional[str] = Field(None, max_length=255)
    utm_term: Optional[str] = Field(None, max_length=255)

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        """Validate event type is one of the allowed types."""
        allowed_types = [
            'view_item',
            'add_to_cart',
            'remove_from_cart',
            'begin_checkout',
            'add_payment_info',
            'add_shipping_info',
            'purchase',
            'refund'
        ]
        if v not in allowed_types:
            raise ValueError(f"event_type must be one of: {', '.join(allowed_types)}")
        return v

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        """Validate currency is uppercase ISO 4217 code."""
        return v.upper()

    @model_validator(mode="after")
    def require_transaction_id_for_purchases(self):
        """Purchases and refunds must carry a transaction_id so the partial
        unique index can deduplicate them — without one, replayed/forged
        purchase events bypass idempotency entirely."""
        if self.event_type in ("purchase", "refund") and not self.transaction_id:
            raise ValueError(f"transaction_id is required for {self.event_type} events")
        return self

    @model_validator(mode="after")
    def require_revenue_for_purchases(self):
        """Purchases and refunds must carry a revenue amount.

        Without this, an integration that sends the wrong field name (e.g.
        `value` instead of `revenue`) gets a silent 200 and a purchase row
        with NULL revenue. That row still counts toward transaction totals
        while contributing nothing to revenue, quietly skewing average order
        value — the failure shows up as bad numbers weeks later rather than
        as an error at integration time."""
        if self.event_type in ("purchase", "refund") and self.revenue is None:
            raise ValueError(f"revenue is required for {self.event_type} events")
        return self

    class Config:
        json_schema_extra = {
            "example": {
                "tracking_code": "a1b2c3d4",
                "event_type": "purchase",
                "event_name": "Product Purchase",
                "transaction_id": "ORDER-2025-001",
                "revenue": 99.99,
                "currency": "USD",
                "tax": 8.00,
                "shipping": 5.99,
                "product_id": "SKU-12345",
                "product_name": "Premium Analytics Dashboard",
                "product_category": "Software/Analytics",
                "product_brand": "Argusmetrics",
                "quantity": 1,
                "price": 99.99,
                "properties": {
                    "payment_method": "credit_card",
                    "coupon": "SAVE20"
                },
                "utm_source": "google",
                "utm_medium": "cpc",
                "utm_campaign": "spring_sale"
            }
        }


class EcommerceEventResponse(BaseModel):
    """Response schema for e-commerce event tracking."""
    success: bool = Field(default=True)
    message: str = Field(default="E-commerce event recorded")
    event_id: Optional[int] = Field(None, description="Event ID if recorded")


class RevenueStatsResponse(BaseModel):
    """Response schema for revenue statistics."""
    total_revenue: Decimal = Field(description="Total revenue")
    total_transactions: int = Field(description="Number of transactions")
    average_order_value: Decimal = Field(description="Average order value")
    total_tax: Decimal = Field(description="Total tax collected")
    total_shipping: Decimal = Field(description="Total shipping fees")
    unique_customers: int = Field(description="Unique customers")
    currency: str = Field(description="Currency code")

    class Config:
        json_schema_extra = {
            "example": {
                "total_revenue": 12450.50,
                "total_transactions": 125,
                "average_order_value": 99.60,
                "total_tax": 996.04,
                "total_shipping": 747.50,
                "unique_customers": 98,
                "currency": "USD"
            }
        }


class ProductStatsItem(BaseModel):
    """Schema for product statistics item."""
    product_id: Optional[str] = Field(None, description="Product ID")
    product_name: str = Field(description="Product name")
    product_category: Optional[str] = Field(None, description="Category")
    units_sold: int = Field(description="Total units sold")
    total_revenue: Decimal = Field(description="Total revenue from product")
    unique_buyers: int = Field(description="Number of unique buyers")


class TopProductsResponse(BaseModel):
    """Response schema for top selling products."""
    products: List[ProductStatsItem] = Field(default_factory=list)
    total_products: int = Field(description="Total unique products")

    class Config:
        json_schema_extra = {
            "example": {
                "products": [
                    {
                        "product_id": "SKU-001",
                        "product_name": "Pro Plan",
                        "product_category": "Subscription",
                        "units_sold": 50,
                        "total_revenue": 4999.50,
                        "unique_buyers": 50
                    }
                ],
                "total_products": 15
            }
        }


class ConversionFunnelResponse(BaseModel):
    """Response schema for conversion funnel analysis."""
    viewed_products: int = Field(description="Users who viewed products")
    added_to_cart: int = Field(description="Users who added to cart")
    cart_rate: float = Field(description="Cart conversion rate (%)")
    started_checkout: int = Field(description="Users who started checkout")
    checkout_rate: float = Field(description="Checkout rate (%)")
    completed_purchase: int = Field(description="Users who purchased")
    purchase_rate: float = Field(description="Purchase rate (%)")
    overall_conversion: float = Field(description="Overall conversion rate (%)")

    class Config:
        json_schema_extra = {
            "example": {
                "viewed_products": 1000,
                "added_to_cart": 300,
                "cart_rate": 30.0,
                "started_checkout": 200,
                "checkout_rate": 66.67,
                "completed_purchase": 150,
                "purchase_rate": 75.0,
                "overall_conversion": 15.0
            }
        }


class RevenueTimeseriesItem(BaseModel):
    """Schema for revenue timeseries data point."""
    date: str = Field(description="Date in YYYY-MM-DD format")
    revenue: Decimal = Field(description="Revenue for the day")
    transactions: int = Field(description="Number of transactions")
    average_order_value: Decimal = Field(description="Average order value")


class RevenueTimeseriesResponse(BaseModel):
    """Response schema for revenue over time."""
    data: List[RevenueTimeseriesItem] = Field(default_factory=list)
    total_revenue: Decimal = Field(description="Total revenue in period")
    total_transactions: int = Field(description="Total transactions in period")

    class Config:
        json_schema_extra = {
            "example": {
                "data": [
                    {
                        "date": "2025-01-01",
                        "revenue": 1250.00,
                        "transactions": 15,
                        "average_order_value": 83.33
                    }
                ],
                "total_revenue": 12500.00,
                "total_transactions": 150
            }
        }
