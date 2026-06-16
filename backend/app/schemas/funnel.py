"""
Funnel schemas for request/response validation.
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class FunnelStep(BaseModel):
    """Schema for a single funnel step."""
    step: int = Field(..., ge=1, description="Step number (1, 2, 3, ...)")
    name: str = Field(..., min_length=1, max_length=255, description="Step name")
    path: str = Field(..., min_length=1, max_length=2000, description="URL path to match")


class CreateFunnelRequest(BaseModel):
    """Request schema for creating a funnel."""
    name: str = Field(..., min_length=1, max_length=255, description="Funnel name")
    steps: List[FunnelStep] = Field(..., min_items=2, description="Funnel steps (minimum 2)")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Checkout Flow",
                "steps": [
                    {"step": 1, "name": "Landing", "path": "/"},
                    {"step": 2, "name": "Product", "path": "/product"},
                    {"step": 3, "name": "Checkout", "path": "/checkout"},
                    {"step": 4, "name": "Thank You", "path": "/thank-you"}
                ]
            }
        }


class FunnelResponse(BaseModel):
    """Response schema for funnel data."""
    id: int
    website_id: int
    name: str
    steps: List[dict]
    created_at: datetime
    is_active: bool

    class Config:
        from_attributes = True


class FunnelStatsResponse(BaseModel):
    """Response schema for funnel conversion statistics."""
    funnel_id: int
    funnel_name: str
    total_visitors: int
    steps: List[dict]  # [{"step": 1, "name": "Landing", "visitors": 100, "conversion_rate": 100}, ...]

    class Config:
        json_schema_extra = {
            "example": {
                "funnel_id": 1,
                "funnel_name": "Checkout Flow",
                "total_visitors": 1000,
                "steps": [
                    {"step": 1, "name": "Landing", "visitors": 1000, "conversion_rate": 100.0},
                    {"step": 2, "name": "Product", "visitors": 500, "conversion_rate": 50.0},
                    {"step": 3, "name": "Checkout", "visitors": 200, "conversion_rate": 20.0},
                    {"step": 4, "name": "Thank You", "visitors": 150, "conversion_rate": 15.0}
                ]
            }
        }
