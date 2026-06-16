"""
Revenue transaction schemas for request/response validation.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class RevenueTrackRequest(BaseModel):
    """Request schema for tracking a revenue transaction."""

    tracking_code: str = Field(..., description="Website tracking code")
    transaction_id: str = Field(..., description="Unique transaction ID from e-commerce platform")
    amount: float = Field(..., gt=0, description="Transaction amount (will be converted to minor units)")
    currency: str = Field(default="USD", min_length=3, max_length=3, description="ISO 4217 currency code")
    product_name: Optional[str] = Field(None, max_length=500, description="Product name")
    product_id: Optional[str] = Field(None, max_length=255, description="Product ID")

    class Config:
        json_schema_extra = {
            "example": {
                "tracking_code": "abc123",
                "transaction_id": "order_12345",
                "amount": 29.99,
                "currency": "USD",
                "product_name": "Premium Analytics Plan",
                "product_id": "plan_pro"
            }
        }


class RevenueTrackResponse(BaseModel):
    """Response schema for revenue tracking."""

    status: str = Field(..., description="Status of the tracking request")
    transaction_id: str = Field(..., description="Transaction ID that was tracked")

    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "transaction_id": "order_12345"
            }
        }
